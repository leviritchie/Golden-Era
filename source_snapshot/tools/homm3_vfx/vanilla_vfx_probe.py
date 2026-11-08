"""Read-only probe of vanilla Olden Era unit / effect prefabs (UnityPy over the installed Golden Era data).

    python tools/homm3_vfx/vanilla_vfx_probe.py tree units/nature/1prefabs/phoenix [more container paths...]
    python tools/homm3_vfx/vanilla_vfx_probe.py json --out artifacts/vanilla_vfx_style/probe.json <paths...>
    python tools/homm3_vfx/vanilla_vfx_probe.py keys --catalog     # rewrite tools/homm3_vfx/native_res_keys.json

Paths are ResourceManager container keys, exactly as the game's resources.assets stores them: Unity writes them
ASCII-lowercased (``units/nature/1prefabs/phoenix``, ``objects/fx/fx_map_fire``) and that exact string is what the
catalogue ships as ``nativeResPath`` for the plugin's ResManager.Get<GameObject> (bundles, then Resources.Load). A path
in any other case, or one missing its root folder (``fx/fx_map_fire``), is refused here instead of silently matched.

For each ResourceManager container path it walks the prefab hierarchy and reports every component, the
MonoBehaviour script class, ParticleSystem main/emission/shape/colour-over-life summaries, renderer
materials with shader names and float/colour/texture properties, and TrailRenderer/LineRenderer settings.
It never writes to the install.

Proof tier: static read of installed serialized assets. It does not show what runtime code does with them.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

GAME = r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/HeroesOldenEra_Data/"
ROOT = Path(__file__).resolve().parents[2]
KEYS_WITNESS = ROOT / "tools/homm3_vfx/native_res_keys.json"
KEYS_SCHEMA = "homm3_native_res_keys.v1"
CATALOG = ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_mesh_fx/catalog.json"

_ENV = None
_CONT = None


def env():
    global _ENV, _CONT
    if _ENV is None:
        import UnityPy
        _ENV = UnityPy.load(GAME + "globalgamemanagers", GAME + "globalgamemanagers.assets", GAME + "resources.assets",
                            GAME + "sharedassets0.assets")
        rm = next(o for o in _ENV.objects if o.type.name == "ResourceManager").read_typetree()
        _CONT = {}
        for k, p in rm["m_Container"]:
            _CONT.setdefault(k, []).append(p)
    return _ENV, _CONT


def container_keys() -> dict:
    """Only the ResourceManager container (globalgamemanagers), without loading resources.assets."""
    import UnityPy
    e = UnityPy.load(GAME + "globalgamemanagers")
    rm = next(o for o in e.objects if o.type.name == "ResourceManager").read_typetree()
    out: dict = {}
    for k, p in rm["m_Container"]:
        out.setdefault(k, []).append(p)
    return out


def lookup(cont: dict, path: str):
    """Exact container key or SystemExit naming the canonical key when only the spelling is wrong."""
    ptrs = cont.get(path)
    if ptrs:
        return ptrs
    near = sorted(k for k in cont if k.lower() == path.lower() or k.endswith("/" + path.lower()))
    hint = f"; canonical key: {near}" if near else ""
    raise SystemExit(f"FAIL: {path!r} is not a ResourceManager container key{hint}")


def resources_file():
    e, _ = env()
    return next(f for n, f in e.files.items() if n.endswith("resources.assets"))


def by_pid(pid):
    return resources_file().objects[pid]


def deref(pptr):
    """Resolve a PPtr dict/obj to an ObjectReader in resources.assets (file 0) or None."""
    if pptr is None:
        return None
    if isinstance(pptr, dict):
        fid, pid = pptr.get("m_FileID", 0), pptr.get("m_PathID", 0)
    else:
        fid, pid = getattr(pptr, "file_id", 0), getattr(pptr, "path_id", 0)
    if not pid:
        return None
    rf = resources_file()
    if fid == 0:
        return rf.objects.get(pid)
    ext = rf.externals[fid - 1].path.rsplit("/", 1)[-1].lower()
    e, _ = env()
    for n, f in e.files.items():
        if n.lower().endswith(ext) and hasattr(f, "objects"):
            return f.objects.get(pid)
    return None


def rnd(v, n=4):
    try:
        return round(float(v), n)
    except Exception:
        return v


def colour(c):
    return [rnd(c[k], 3) for k in ("r", "g", "b", "a")] if isinstance(c, dict) else c


def material_info(mref, cache):
    if mref is None:
        return None
    key = mref.path_id
    if key in cache:
        return cache[key]
    tt = mref.read_typetree()
    sh = deref(tt.get("m_Shader"))
    shader_name = None
    if sh is not None:
        try:
            st = sh.read_typetree()
            shader_name = st.get("m_ParsedForm", {}).get("m_Name") or st.get("m_Name")
        except Exception as ex:  # noqa: BLE001
            shader_name = f"<unreadable {ex}>"
    props = tt.get("m_SavedProperties", {})
    texs = {}
    for name, te in props.get("m_TexEnvs", []):
        t = deref(te.get("m_Texture"))
        if t is not None:
            try:
                ttt = t.read_typetree()
                texs[name] = {"name": ttt.get("m_Name"), "pid": t.path_id, "w": ttt.get("m_Width"),
                              "h": ttt.get("m_Height"), "scale": [rnd(te["m_Scale"]["x"]), rnd(te["m_Scale"]["y"])],
                              "offset": [rnd(te["m_Offset"]["x"]), rnd(te["m_Offset"]["y"])]}
            except Exception:
                texs[name] = {"pid": t.path_id}
    info = {
        "name": tt.get("m_Name"), "pid": key, "shader": shader_name,
        "keywords": tt.get("m_ValidKeywords") or tt.get("m_ShaderKeywords"),
        "renderQueue": tt.get("m_CustomRenderQueue"),
        "tags": tt.get("stringTagMap"),
        "textures": texs,
        "floats": {k: rnd(v) for k, v in props.get("m_Floats", [])},
        "colors": {k: colour(v) for k, v in props.get("m_Colors", [])},
    }
    cache[key] = info
    return info


def ps_summary(tt):
    out = {}
    try:
        out["duration"] = rnd(tt.get("lengthInSec"))
        out["looping"] = bool(tt.get("looping"))
        out["prewarm"] = bool(tt.get("prewarm"))
        out["scalingMode"] = tt.get("scalingMode")
        out["playOnAwake"] = tt.get("playOnAwake")
        out["startDelay"] = rnd(tt.get("startDelay", {}).get("scalar"))
        im = tt.get("InitialModule", {})
        for f in ("startLifetime", "startSpeed", "startSize", "startRotation"):
            c = im.get(f, {})
            out[f] = {"mode": c.get("minMaxState"), "scalar": rnd(c.get("scalar")), "min": rnd(c.get("minScalar"))}
        sc = im.get("startColor", {})
        out["startColor"] = {"mode": sc.get("minMaxState"), "max": colour(sc.get("maxColor")), "min": colour(sc.get("minColor"))}
        out["maxParticles"] = im.get("maxNumParticles")
        out["gravity"] = rnd(im.get("gravityModifier", {}).get("scalar"))
        out["simSpace"] = tt.get("moveWithTransform")
        em = tt.get("EmissionModule", {})
        out["emission"] = {"enabled": em.get("enabled"), "rate": rnd(em.get("rateOverTime", {}).get("scalar")),
                           "rateDist": rnd(em.get("rateOverDistance", {}).get("scalar")),
                           "bursts": [{"t": rnd(b.get("time")), "n": rnd(b.get("countCurve", {}).get("scalar"))}
                                      for b in em.get("m_Bursts", [])]}
        sh = tt.get("ShapeModule", {})
        out["shape"] = {"enabled": sh.get("enabled"), "type": sh.get("type"), "radius": rnd(sh.get("radius", {}).get("value") if isinstance(sh.get("radius"), dict) else sh.get("radius")),
                        "angle": rnd(sh.get("angle")), "mesh": bool(sh.get("m_Mesh", {}).get("m_PathID")) if isinstance(sh.get("m_Mesh"), dict) else None}
        mods = []
        for m in ("ColorModule", "SizeModule", "RotationModule", "VelocityModule", "NoiseModule", "UVModule",
                  "TrailModule", "LightsModule", "SubModule", "ForceModule", "ClampVelocityModule",
                  "CustomDataModule", "ColorBySpeedModule", "SizeBySpeedModule", "CollisionModule"):
            if tt.get(m, {}).get("enabled"):
                mods.append(m)
        out["modules"] = mods
        uv = tt.get("UVModule", {})
        if uv.get("enabled"):
            out["uv"] = {"tilesX": uv.get("tilesX"), "tilesY": uv.get("tilesY"), "cycles": rnd(uv.get("cycles")),
                         "mode": uv.get("animationType")}
        cm = tt.get("ColorModule", {})
        if cm.get("enabled"):
            g = cm.get("gradient", {}).get("maxGradient", {})
            keys = []
            for i in range(g.get("m_NumColorKeys", 0)):
                c = g.get(f"key{i}")
                keys.append([rnd(g.get(f"ctime{i}", 0) / 65535, 3)] + colour(c)[:3])
            akeys = [[rnd(g.get(f"atime{i}", 0) / 65535, 3), rnd(g.get(f"key{i}", {}).get("a"), 3)]
                     for i in range(g.get("m_NumAlphaKeys", 0))]
            out["colorOverLife"] = {"rgb": keys, "alpha": akeys}
        lm = tt.get("LightsModule", {})
        if lm.get("enabled"):
            out["lights"] = {"ratio": rnd(lm.get("ratio")), "maxLights": lm.get("maxLights"),
                             "intensity": rnd(lm.get("intensityCurve", {}).get("scalar")),
                             "range": rnd(lm.get("rangeCurve", {}).get("scalar"))}
    except Exception as ex:  # noqa: BLE001
        out["error"] = str(ex)
    return out


def script_name(tt):
    s = deref(tt.get("m_Script"))
    if s is None:
        return None
    try:
        st = s.read_typetree()
        return f"{st.get('m_Namespace', '')}.{st.get('m_ClassName')}".lstrip(".")
    except Exception:
        return "<script?>"


def mb_script_raw(reader):
    """IL2CPP builds strip MonoBehaviour field typetrees; the base header is fixed:
    PPtr<GameObject>(int32 fileID, int64 pathID), UInt8 enabled + 3 pad, PPtr<MonoScript>."""
    import struct
    raw = reader.get_raw_data()
    fid, pid = struct.unpack_from("<iq", raw, 16)
    return script_name({"m_Script": {"m_FileID": fid, "m_PathID": pid}})


def walk(go_reader, depth, mats, out, max_depth=40):
    go = go_reader.read_typetree()
    node = {"name": go.get("m_Name"), "active": go.get("m_IsActive"), "layer": go.get("m_Layer"), "components": [], "children": []}
    transform = None
    for c in go.get("m_Component", []):
        cr = deref(c["component"])
        if cr is None:
            continue
        tn = cr.type.name
        comp = {"type": tn}
        try:
            tt = cr.read_typetree()
        except Exception as ex:  # noqa: BLE001
            if tn == "MonoBehaviour":
                comp["script"] = mb_script_raw(cr)
            else:
                comp["error"] = str(ex)
            node["components"].append(comp)
            continue
        if tn in ("Transform", "RectTransform"):
            transform = tt
            comp["pos"] = [rnd(tt["m_LocalPosition"][k], 3) for k in "xyz"]
            comp["scale"] = [rnd(tt["m_LocalScale"][k], 3) for k in "xyz"]
            continue  # children handled below
        if tn == "MonoBehaviour":
            comp["script"] = script_name(tt) if tt.get("m_Script") else None
            comp["enabled"] = tt.get("m_Enabled")
            extra = {k: v for k, v in tt.items() if not k.startswith("m_") or k in ("m_Name",)}
            if extra:
                comp["fields"] = _compact(extra)
        elif tn == "ParticleSystem":
            comp.update(ps_summary(tt))
        elif tn in ("ParticleSystemRenderer", "MeshRenderer", "SkinnedMeshRenderer", "TrailRenderer", "LineRenderer"):
            comp["enabled"] = tt.get("m_Enabled")
            comp["materials"] = [material_info(deref(m), mats) and deref(m).path_id for m in tt.get("m_Materials", [])]
            if tn == "ParticleSystemRenderer":
                comp["renderMode"] = tt.get("m_RenderMode")
                comp["sortingFudge"] = rnd(tt.get("m_SortingFudge"))
                comp["maxParticleSize"] = rnd(tt.get("m_MaxParticleSize"))
                comp["alignment"] = tt.get("m_RenderAlignment")
                comp["mesh"] = bool(tt.get("m_Mesh", {}).get("m_PathID"))
            if tn in ("TrailRenderer",):
                comp["time"] = rnd(tt.get("m_Time"))
                comp["minVertexDistance"] = rnd(tt.get("m_MinVertexDistance"))
        elif tn == "Light":
            comp.update({"lightType": tt.get("m_Type"), "color": colour(tt.get("m_Color")), "intensity": rnd(tt.get("m_Intensity")),
                         "range": rnd(tt.get("m_Range")), "shadows": tt.get("m_Shadows", {}).get("m_Type")})
        elif tn in ("Animator", "Animation", "PlayableDirector", "AudioSource", "MeshFilter"):
            if tn == "PlayableDirector":
                pa = deref(tt.get("m_PlayableAsset"))
                comp["playable"] = None
                if pa is not None:
                    comp["playable"] = f"{pa.type.name}#{pa.path_id}:{mb_script_raw(pa)}" if pa.type.name == "MonoBehaviour" else pa.type.name
                comp["playOnAwake"] = tt.get("m_InitialState")
                comp["wrapMode"] = tt.get("m_WrapMode")
            if tn == "MeshFilter":
                mr = deref(tt.get("m_Mesh"))
                comp["mesh"] = mr.read_typetree().get("m_Name") if mr is not None else None
        node["components"].append(comp)
    if transform is not None and transform.get("m_Children") and depth >= max_depth:
        # fail closed: the old silent 12-level cut dropped the angel's Spear/Angel_close_hit_Spear children
        raise RuntimeError(f"{node['name']}: hierarchy deeper than max_depth={max_depth}; raise it, never truncate")
    if transform is not None:
        for ch in transform.get("m_Children", []):
            tr = deref(ch)
            if tr is None:
                continue
            cgo = deref(tr.read_typetree()["m_GameObject"])
            if cgo is not None:
                node["children"].append(walk(cgo, depth + 1, mats, out, max_depth))
    return node


def _compact(d, lim=40):
    """Keep MonoBehaviour fields readable: PPtrs become names where resolvable, long lists get trimmed."""
    def conv(v, depth=0):
        if isinstance(v, dict):
            if set(v.keys()) >= {"m_FileID", "m_PathID"}:
                r = deref(v)
                if r is None:
                    return None if not v["m_PathID"] else f"<ext {v['m_FileID']}:{v['m_PathID']}>"
                try:
                    nm = r.read_typetree().get("m_Name")
                except Exception:
                    nm = None
                if r.type.name == "GameObject" or nm:
                    return f"{r.type.name}:{nm}"
                if r.type.name == "Transform":
                    try:
                        g = deref(r.read_typetree()["m_GameObject"]).read_typetree()["m_Name"]
                        return f"Transform:{g}"
                    except Exception:
                        pass
                return f"{r.type.name}#{r.path_id}"
            if depth > 5:
                return "..."
            return {k: conv(x, depth + 1) for k, x in v.items()}
        if isinstance(v, list):
            vv = [conv(x, depth + 1) for x in v[:lim]]
            if len(v) > lim:
                vv.append(f"... +{len(v) - lim}")
            return vv
        if isinstance(v, float):
            return rnd(v)
        return v
    return conv(d)


def probe(path):
    _, cont = env()
    ptrs = lookup(cont, path)
    results = []
    for p in ptrs:
        r = resources_file().objects.get(p["m_PathID"])
        if r is None:
            continue
        if r.type.name != "GameObject":
            results.append({"path": path, "type": r.type.name, "pid": r.path_id})
            continue
        mats = {}
        tree = walk(r, 0, mats, None)
        results.append({"path": path, "type": "GameObject", "pid": r.path_id, "tree": tree, "materials": mats})
    return results


def _interesting(node):
    return bool(node["components"]) or any(_interesting(c) for c in node["children"])


def print_tree(node, mats, ind=0):
    if ind and not _interesting(node):
        return
    pad = "  " * ind
    comps = []
    for c in node["components"]:
        t = c["type"]
        if t == "MonoBehaviour":
            t = f"MB<{c.get('script')}>"
        elif t == "ParticleSystem":
            t = (f"PS(dur={c.get('duration')} loop={c.get('looping')} life={c.get('startLifetime', {}).get('scalar')} "
                 f"size={c.get('startSize', {}).get('scalar')} rate={c.get('emission', {}).get('rate')} "
                 f"bursts={c.get('emission', {}).get('bursts')} col={c.get('startColor', {}).get('max')} mods={c.get('modules')})")
        elif "materials" in c:
            ms = [(mats.get(m) or {}).get("shader") for m in c["materials"] if m]
            mn = [(mats.get(m) or {}).get("name") for m in c["materials"] if m]
            t = f"{t}(mat={mn} sh={ms} mode={c.get('renderMode')})"
        elif t == "Light":
            t = f"Light(type={c.get('lightType')} col={c.get('color')} I={c.get('intensity')} R={c.get('range')})"
        elif t == "MeshFilter":
            t = f"MeshFilter({c.get('mesh')})"
        elif t == "PlayableDirector":
            t = f"PlayableDirector({c.get('playable')})"
        comps.append(t)
    print(f"{pad}{node['name']}{'' if node['active'] else ' [inactive]'}: {'; '.join(comps)}")
    for ch in node["children"]:
        print_tree(ch, mats, ind + 1)


def catalog_res_paths() -> list[str]:
    cat = json.loads(CATALOG.read_text(encoding="utf-8"))
    return sorted({((r.get("source") or {}).get("nativeResPath") or "") for r in cat["entries"]} - {""})


def write_keys_witness(paths: list[str]) -> None:
    """Static witness the build validators check nativeResPath against (they never read the install)."""
    cont = container_keys()
    keys = {p: [int(x["m_PathID"]) for x in lookup(cont, p)] for p in sorted(set(paths))}
    stat = os.stat(GAME + "globalgamemanagers")
    out = {"schema": KEYS_SCHEMA, "game": GAME,
           "proof": "static read of the installed ResourceManager container (globalgamemanagers); not runtime",
           "keyForm": "exact m_Container key (Unity stores them ASCII-lowercased; the plugin passes this string to "
                      "ResManager.Get<GameObject>, which falls back to Resources.Load)",
           "globalgamemanagersBytes": stat.st_size, "containerKeyCount": sum(len(v) for v in cont.values()),
           "keys": keys}
    KEYS_WITNESS.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"keys: {len(keys)} path(s) -> {KEYS_WITNESS.relative_to(ROOT).as_posix()}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["tree", "json", "keys"])
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--out")
    ap.add_argument("--catalog", action="store_true", help="keys: witness every nativeResPath in homm3_mesh_fx/catalog.json")
    a = ap.parse_args()
    if a.mode == "keys":
        write_keys_witness(list(a.paths) + (catalog_res_paths() if a.catalog else []))
        return
    allres = []
    for p in a.paths:
        res = probe(p)
        allres.extend(res)
        if a.mode == "tree":
            for r in res:
                if r["type"] != "GameObject":
                    print(f"== {p}: {r['type']} #{r['pid']}")
                    continue
                print(f"== {p} (#{r['pid']})")
                print_tree(r["tree"], r["materials"])
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(allres, f, indent=1, default=str)
        print(f"wrote {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
