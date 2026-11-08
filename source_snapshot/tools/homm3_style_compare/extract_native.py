"""Extract vanilla Olden Era battle units (mesh posed at idle t=0, native textures, material props) read-only.

    python tools/homm3_style_compare/extract_native.py --out artifacts/homm3_style_compare/native \
        humans/1prefabs/esquire humans/1prefabs/crossbowman ...

Opens the installed game's `globalgamemanagers` (ResourceManager container: `units/<path>` -> prefab) and
`resources.assets` with UnityPy; never writes to the install. Per prefab it writes <out>/<name>/:
  mesh.npz     pos (N,3) / nrm (N,3) Unity world (prefab root) space after skinning at the idle clip's t=0
               (bones not driven by the clip keep the prefab pose), uv (N,2), tri (M,3), mat (M,) material index
  mat_<i>.png  each material's main texture (the albedo the native shader samples)
  meta.json    shader + every texture / float / colour property per material, view scale, heights, counts
Battle size: UiModelsSpawner overwrites the prefab's first child localScale magnitude with UnitViewConfig.scale
(tools/custom_prefab_pipeline/ESQUIRE_STOCK_VISUAL_CONTRACT.md); the same rule is applied here, so `pos` is the
unit's world size in battle under that contract (assumption: battle spawns use the same first-child rule).
Proof tier: static read of the installed assets; the pose is a decoded clip sample, not a runtime capture.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import zipfile
import zlib

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "homm3_idle_cadence"))
from measure_native_idles import decode_streamed, eval_streamed  # noqa: E402

GAME = r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/HeroesOldenEra_Data/"
MAIN_TEX = ("_MainTex", "_BaseMap", "_BaseColorMap", "_Albedo", "_Diffuse")


def quat_mat(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def trs(t, q, s):
    m = np.eye(4)
    m[:3, :3] = quat_mat(q) * np.asarray(s)[None, :]
    m[:3, 3] = t
    return m


def clip_sample0(tt):
    """Every generic Transform curve of a muscle clip at its start time: {pathHash: {attr: values}}
    (attr 1 = position xyz, 2 = rotation xyzw, 3 = scale xyz, 4 = euler; as measure_native_idles.clip_rotations)."""
    mc = tt["m_MuscleClip"]
    t0 = np.array([float(mc["m_StartTime"])])
    data = mc["m_Clip"]["data"]
    sc = data["m_StreamedClip"]; dc = data["m_DenseClip"]; cc = data["m_ConstantClip"]["data"]
    n_s = int(sc["curveCount"]); n_d = int(dc["m_CurveCount"])
    streamed = decode_streamed(sc["data"]) if sc["data"] else {}
    dense = np.asarray(dc["m_SampleArray"], dtype=np.float64)
    if n_d:
        dense = dense.reshape(int(dc["m_FrameCount"]), n_d)

    def curve(i):
        if i < n_s:
            k = streamed.get(i)
            return float(eval_streamed(k, t0)[0]) if k else 0.0
        i -= n_s
        if i < n_d:
            return float(dense[0, i])
        return float(cc[i - n_d])

    out, ci = {}, 0
    for b in tt["m_ClipBindingConstant"]["genericBindings"]:
        if b["typeID"] == 4:
            size = 4 if b["attribute"] == 2 else 3
            out.setdefault(str(b["path"]), {})[int(b["attribute"])] = [curve(ci + k) for k in range(size)]
        else:
            size = 1
        ci += size
    return out


def views_by_mesh():
    z = zipfile.ZipFile(GAME + "StreamingAssets/Core.zip")
    out = {}
    for n in z.namelist():
        if not (n.startswith("DB/units/units_views/") and n.endswith(".json")) or "/homm3_" in n:
            continue
        try:
            arr = json.loads(z.read(n).decode("utf-8-sig")).get("array", [])
        except Exception:
            continue
        for v in arr:
            if isinstance(v, dict) and "mesh" in v:
                out[v["mesh"].lower()] = {"id": v.get("id"), "scale": v.get("scale"), "modelHeight": v.get("modelHeight"),
                                          "defaultHeight": v.get("defaultHeight")}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-pose", action="store_true", help="keep the prefab's own pose (diagnostic)")
    ap.add_argument("prefabs", nargs="+", help="container path under units/, e.g. humans/1prefabs/esquire; suffix "
                    "@authored for a prefab no unit view uses (keeps the prefab's own first-child scale, recorded)")
    a = ap.parse_args()
    import UnityPy
    from UnityPy.helpers.MeshHelper import MeshHandler
    env = UnityPy.load(GAME + "globalgamemanagers", GAME + "resources.assets")
    rm = next(o for o in env.objects if o.type.name == "ResourceManager").read_typetree()
    cont = {k.lower(): p for k, p in rm["m_Container"]}
    ra = next(f for n, f in env.files.items() if n.endswith("resources.assets"))
    views = views_by_mesh()

    def obj(pid):
        return ra.objects[pid]

    for pref in a.prefabs:
        authored = pref.endswith("@authored")
        pref = pref.removesuffix("@authored")
        key = "units/" + pref.lower()
        if key not in cont:
            sys.exit(f"FAIL: {key} not in the ResourceManager container")
        root = obj(cont[key]["m_PathID"])
        name = pref.rsplit("/", 1)[-1]
        view = views.get(pref.lower())
        if view is None and not authored:
            sys.exit(f"FAIL: no Core.zip unit view uses mesh {pref} (pass {pref}@authored to keep the prefab scale)")
        if view is not None and authored:
            sys.exit(f"FAIL: {pref} has a unit view; drop @authored")
        # ---- transform tree
        nodes = {}  # transform pid -> {go, name, t, q, s, parent, children}

        def comps(go_tt):
            for c in go_tt["m_Component"]:
                pid = c["component"]["m_PathID"]
                if c["component"]["m_FileID"] == 0 and pid in ra.objects:
                    yield ra.objects[pid]

        def visit(tr_pid, parent):
            o = obj(tr_pid)
            tt = o.read_typetree()
            go = obj(tt["m_GameObject"]["m_PathID"]).read_typetree()
            v = lambda d, k: [d[k][c] for c in ("x", "y", "z", "w") if c in d[k]]
            nodes[tr_pid] = {"name": go["m_Name"], "go": tt["m_GameObject"]["m_PathID"], "t": v(tt, "m_LocalPosition"),
                             "q": v(tt, "m_LocalRotation"), "s": v(tt, "m_LocalScale"), "parent": parent,
                             "children": [c["m_PathID"] for c in tt["m_Children"]], "goTT": go}
            for c in tt["m_Children"]:
                visit(c["m_PathID"], tr_pid)

        rtt = root.read_typetree()
        rtr = next(c for c in comps(rtt) if c.type.name in ("Transform", "RectTransform"))
        visit(rtr.path_id, None)
        first = nodes[rtr.path_id]["children"][0]
        fs = nodes[first]["s"]
        if view is not None:
            nodes[first]["s"] = [math.copysign(float(view["scale"]), x) for x in fs]
        else:
            view = {"id": None, "scale": None, "note": "no unit view uses this prefab; authored first-child scale kept"}

        def path_of(pid, stop):
            parts = []
            while pid is not None and pid != stop:
                parts.append(nodes[pid]["name"]); pid = nodes[pid]["parent"]
            return "/".join(reversed(parts))

        # ---- idle pose t=0
        posed, idle_clip = 0, None
        for pid, n in nodes.items():
            for c in comps(n["goTT"]):
                if c.type.name != "Animator":
                    continue
                an = c.read_typetree()
                ctrl = ra.objects.get(an["m_Controller"]["m_PathID"])
                if ctrl is None or ctrl.type.name != "AnimatorOverrideController":
                    continue
                ctt = ctrl.read_typetree()
                for cl in ctt["m_Clips"]:
                    orig = ra.objects.get(cl["m_OriginalClip"]["m_PathID"]); ov = ra.objects.get(cl["m_OverrideClip"]["m_PathID"])
                    if orig is not None and ov is not None and orig.peek_name() == "22.Idle" and not a.no_pose:
                        curves = clip_sample0(ov.read_typetree())
                        idle_clip = ov.peek_name()
                        byhash = {}
                        stack = [pid]
                        while stack:
                            p = stack.pop(); stack += nodes[p]["children"]
                            if p != pid:
                                byhash[str(zlib.crc32(path_of(p, pid).encode()))] = p
                        for h, attrs in curves.items():
                            if h not in byhash:
                                continue
                            nd_ = nodes[byhash[h]]
                            if 2 in attrs:
                                q = np.asarray(attrs[2]); q = q / max(np.linalg.norm(q), 1e-9)
                                nd_["q"] = [float(x) for x in q]
                            if 1 in attrs:
                                nd_["t"] = attrs[1]
                            if 3 in attrs:
                                nd_["s"] = attrs[3]
                            posed += 1
        world = {}

        def wm(pid):
            if pid not in world:
                n = nodes[pid]
                m = trs(n["t"], n["q"], n["s"])
                world[pid] = m if n["parent"] is None else wm(n["parent"]) @ m
            return world[pid]

        # ---- renderers
        P, N, UV, T, MI, mats = [], [], [], [], [], []
        base = 0
        renderers = []
        for pid, n in nodes.items():
            for c in comps(n["goTT"]):
                if c.type.name not in ("SkinnedMeshRenderer", "MeshRenderer"):
                    continue
                rtt_ = c.read_typetree()
                if not rtt_.get("m_Enabled", 1) or not n["goTT"].get("m_IsActive", 1):
                    continue
                if c.type.name == "SkinnedMeshRenderer":
                    mesh_pid = rtt_["m_Mesh"]["m_PathID"]
                else:
                    mf = next((x for x in comps(n["goTT"]) if x.type.name == "MeshFilter"), None)
                    mesh_pid = mf.read_typetree()["m_Mesh"]["m_PathID"] if mf else 0
                if mesh_pid not in ra.objects:
                    continue
                mesh = ra.objects[mesh_pid].read()
                h = MeshHandler(mesh); h.process()
                v = np.asarray(h.m_Vertices, dtype=np.float64)[:, :3]
                nr = np.asarray(h.m_Normals, dtype=np.float64)[:, :3] if h.m_Normals else np.zeros_like(v)
                uv = np.asarray(h.m_UV0, dtype=np.float64)[:, :2] if h.m_UV0 else np.zeros((len(v), 2))
                if c.type.name == "SkinnedMeshRenderer" and rtt_["m_Bones"] and h.m_BoneIndices:
                    bind = [np.array([[getattr(b, f"e{r}{cc}") for cc in range(4)] for r in range(4)])
                            for b in mesh.m_BindPose]
                    bones = [b["m_PathID"] for b in rtt_["m_Bones"]]
                    skin = np.stack([wm(b) @ bind[i] if b in nodes else np.eye(4) for i, b in enumerate(bones)])
                    # a mesh with one influence per vertex stores BlendIndices only (dimension 1, no BlendWeight)
                    k = max(len(x) for x in h.m_BoneIndices[:64])
                    bi = np.zeros((len(v), 4), dtype=np.int64); bi[:, :k] = np.asarray(h.m_BoneIndices, dtype=np.int64)[:, :4]
                    bw = np.zeros((len(v), 4))
                    if h.m_BoneWeights:
                        w = np.asarray(h.m_BoneWeights, dtype=np.float64); bw[:, :w.shape[1]] = w[:, :4]
                    else:
                        bw[:, 0] = 1.0
                    bw = bw / np.maximum(bw.sum(1, keepdims=True), 1e-9)
                    vh = np.c_[v, np.ones(len(v))]
                    M = np.einsum("vk,vkij->vij", bw, skin[bi])
                    vw = np.einsum("vij,vj->vi", M, vh)[:, :3]
                    nw = np.einsum("vij,vj->vi", M[:, :3, :3], nr)
                else:
                    M = wm(pid)
                    vw = (M @ np.c_[v, np.ones(len(v))].T).T[:, :3]
                    nw = (M[:3, :3] @ nr.T).T
                nw /= np.maximum(np.linalg.norm(nw, axis=1, keepdims=True), 1e-9)
                tris = h.get_triangles()
                for si, sub in enumerate(tris):
                    if si >= len(rtt_["m_Materials"]):
                        break
                    mpid = rtt_["m_Materials"][si]["m_PathID"]
                    if mpid not in ra.objects:
                        continue
                    t = np.asarray(sub, dtype=np.int64).reshape(-1, 3)
                    mats.append(mpid); MI.append(np.full(len(t), len(mats) - 1)); T.append(t + base)
                P.append(vw); N.append(nw); UV.append(uv); base += len(v)
                renderers.append({"go": n["name"], "type": c.type.name, "mesh": mesh.m_Name, "vertices": len(v),
                                  "triangles": int(sum(len(s) // 3 if not isinstance(s[0], (tuple, list)) else len(s)
                                                       for s in tris))})
        if not P:
            sys.exit(f"FAIL: {pref}: no enabled renderer with a mesh")
        od = os.path.join(a.out, name); os.makedirs(od, exist_ok=True)
        mat_meta = []
        for i, mpid in enumerate(mats):
            m = ra.objects[mpid].read_typetree()
            sh = ra.objects.get(m["m_Shader"]["m_PathID"])
            shname = None
            if sh is not None:
                try:
                    shname = sh.read().m_ParsedForm.m_Name
                except Exception:
                    shname = sh.peek_name()
            props = m["m_SavedProperties"]
            texs, main = {}, None
            for tk, tv in props["m_TexEnvs"]:
                tp = tv["m_Texture"]["m_PathID"]
                if tp and tp in ra.objects:
                    texs[tk] = ra.objects[tp].peek_name()
                    if main is None and tk in MAIN_TEX:
                        main = tp
            png = emi = None
            if main is not None:
                img = ra.objects[main].read().image
                png = f"mat_{i}.png"; img.save(os.path.join(od, png))
            et = next((tv["m_Texture"]["m_PathID"] for tk, tv in props["m_TexEnvs"] if tk == "_EmissionTex"), 0)
            if et and et in ra.objects:
                emi = f"emi_{i}.png"; ra.objects[et].read().image.save(os.path.join(od, emi))
            mat_meta.append({"name": m["m_Name"], "shader": shname, "mainTexture": png, "emissionTexture": emi,
                             "textures": texs,
                             "floats": {k: v for k, v in props["m_Floats"]},
                             "colors": {k: [v["r"], v["g"], v["b"], v["a"]] for k, v in props["m_Colors"]},
                             "keywords": m.get("m_ValidKeywords") or m.get("m_ShaderKeywords")})
        pos = np.concatenate(P); nrm = np.concatenate(N); uv = np.concatenate(UV)
        tri = np.concatenate(T); mi = np.concatenate(MI)
        np.savez_compressed(os.path.join(od, "mesh.npz"), pos=pos.astype(np.float32), nrm=nrm.astype(np.float32),
                            uv=uv.astype(np.float32), tri=tri.astype(np.int32), mat=mi.astype(np.int32))
        used = np.unique(tri)
        lo, hi = pos[used].min(0), pos[used].max(0)
        meta = {"schema": "homm3_style_compare.native.v1", "prefab": "units/" + pref, "name": name, "view": view,
                "firstChildScaleAuthored": fs, "idleClip": idle_clip, "posedBones": posed,
                "renderers": renderers, "materials": mat_meta, "vertices": int(len(used)), "triangles": int(len(tri)),
                "boundsUnity": {"min": lo.tolist(), "max": hi.tolist()}, "worldHeight": float(hi[1] - lo[1]),
                "source": GAME + "resources.assets"}
        json.dump(meta, open(os.path.join(od, "meta.json"), "w"), indent=1)
        # every transform's posed world matrix (same space as mesh.npz pos), keyed by GameObject name; used to hang
        # reference effects on vanilla bones (tools/homm3_vfx/vanilla_style_lab.py)
        json.dump({"schema": "homm3_style_compare.native_bones.v1",
                   "bones": {nodes[p]["name"]: wm(p).tolist() for p in nodes}},
                  open(os.path.join(od, "bones.json"), "w"))
        print(f"NATIVE {name}: {len(used)} verts {len(tri)} tris h={hi[1]-lo[1]:.3f} posed={posed} "
              f"shaders={sorted({m['shader'] for m in mat_meta if m['shader']})}", flush=True)


if __name__ == "__main__":
    main()
