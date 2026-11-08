"""Convert vanilla Olden Era effect subtrees into lab ParticleSystem recipes (read-only over the installed assets).

    python tools/homm3_vfx/vanilla_ps_recipe.py <out_dir> <container_path>[:<node name>[/<node name>...]] ...

A recipe is the vanilla ParticleSystem / ParticleSystemRenderer serialized state, normalised so the Unity lab
(tools/homm3_vfx/unity/Homm3VanillaStyleVfxLab.cs) can rebuild the same systems with the public ParticleSystem API:

  MinMaxCurve    {mode, scalar, minScalar, maxKeys, minKeys}   keys flattened [time, value, inSlope, outSlope]...
                 mode 0 constant, 1 curve x scalar, 2 two curves x scalar, 3 two constants (minScalar..scalar)
  MinMaxGradient {mode, maxColor, minColor, maxC, maxA, minC, minA, gradMode}   keys flattened [t, r, g, b] / [t, a]
  node           transform (local pos / quat / scale), active flag, the modules the lab supports, renderer,
                 material names; nodes are listed parent-first and reference their parent by index. A (Skinned)MeshRenderer node
                 lists its materials as `meshMaterials` (bodyOverlay sources; the lab appends them to the body).

Materials (shader name, keywords, textures with scale/offset, floats, colours) go to <out>/materials.json and their
textures to <out>/tex/<name>.png with the texture's colour space and wrap mode; meshes used by Mesh-mode renderers
go to <out>/mesh/<name>.obj. The root keeps its local transform under `parentName` (the bone it hangs from). Only active nodes are kept unless the path names an inactive root explicitly (its
inactive descendants are still dropped, as the game never shows them without a Timeline activating them).

Each recipe is written to <out>/<recipe_key(source)>.json. The key is the source with "/" and ":" as "__"; a key
longer than KEY_MAX keeps a readable prefix and ends in a hash of the full source, because Unity's Mono FileStream
refuses paths of 260 characters or more (the recipes folder alone is ~70). recipe_key is the one owner of that rule;
the lab imports it.

Proof tier: static read of installed serialized assets. The lab rebuild is an editor replica, not the game.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import vanilla_vfx_probe as V  # noqa: E402

MODULE_KEYS = ("ColorModule", "SizeModule", "RotationModule", "VelocityModule", "NoiseModule", "UVModule",
               "TrailModule", "LightsModule", "ClampVelocityModule", "SubModule", "ForceModule",
               "InheritVelocityModule", "CustomDataModule", "CollisionModule", "ColorBySpeedModule",
               "SizeBySpeedModule", "RotationBySpeedModule", "ExternalForcesModule", "TriggerModule",
               "LifetimeByEmitterSpeedModule")
SUPPORTED = {"ColorModule", "SizeModule", "RotationModule", "VelocityModule", "NoiseModule", "UVModule",
             "TrailModule", "LightsModule", "ClampVelocityModule", "SubModule", "ForceModule", "CustomDataModule"}


KEY_MAX = 120      # recipe file stem limit: 70-char folder + 120 + ".json" stays far under Unity's 260
KEY_PREFIX = 100   # readable part kept before the hash of a long key


def recipe_key(source: str) -> str:
    """Deterministic recipe file stem for a `<resPath>[:<childPath>]` source (see the module docstring)."""
    key = source.replace("/", "__").replace(":", "__")
    if len(key) <= KEY_MAX:
        return key
    return key[:KEY_PREFIX] + "__h" + hashlib.sha1(source.encode("utf-8")).hexdigest()[:16]


def keys(curve):
    out = []
    for k in (curve or {}).get("m_Curve", []):
        out += [float(k["time"]), float(k["value"]), float(k["inSlope"]), float(k["outSlope"])]
    return out


def mmc(d):
    d = d or {}
    return {"mode": int(d.get("minMaxState", 0)), "scalar": float(d.get("scalar", 0.0)),
            "minScalar": float(d.get("minScalar", 0.0)), "maxKeys": keys(d.get("maxCurve")),
            "minKeys": keys(d.get("minCurve"))}


def const(v):
    return {"mode": 0, "scalar": float(v), "minScalar": float(v), "maxKeys": [], "minKeys": []}


def _grad(g):
    c, a = [], []
    for i in range(int(g.get("m_NumColorKeys", 0))):
        k = g[f"key{i}"]
        c += [g.get(f"ctime{i}", 0) / 65535.0, k["r"], k["g"], k["b"]]
    for i in range(int(g.get("m_NumAlphaKeys", 0))):
        a += [g.get(f"atime{i}", 0) / 65535.0, g[f"key{i}"]["a"]]
    return c, a, int(g.get("m_Mode", 0))


def mmg(d):
    d = d or {}
    col = lambda c: [float(c[k]) for k in "rgba"] if c else [1.0, 1.0, 1.0, 1.0]
    maxc, maxa, gm = _grad(d.get("maxGradient", {}))
    minc, mina, _ = _grad(d.get("minGradient", {}))
    return {"mode": int(d.get("minMaxState", 0)), "maxColor": col(d.get("maxColor")), "minColor": col(d.get("minColor")),
            "maxC": maxc, "maxA": maxa, "minC": minc, "minA": mina, "gradMode": gm}


def v3(d):
    return [float(d["x"]), float(d["y"]), float(d["z"])]


class Extractor:
    def __init__(self, out: Path):
        self.out = out
        (out / "tex").mkdir(parents=True, exist_ok=True)
        (out / "mesh").mkdir(parents=True, exist_ok=True)
        self.materials = {}
        self.meshes = {}
        self.textures = {}

    # ---------------------------------------------------------------- assets
    def texture(self, reader):
        tt = reader.read_typetree()
        name = tt["m_Name"]
        if name not in self.textures:
            p = self.out / "tex" / f"{name}.png"
            if not p.exists():
                reader.read().image.save(p)
            ts = tt.get("m_TextureSettings", {})
            self.textures[name] = {"file": f"tex/{name}.png", "w": tt.get("m_Width"), "h": tt.get("m_Height"),
                                   "sRGB": int(tt.get("m_ColorSpace", 1)) == 1, "wrapU": ts.get("m_WrapU", 0),
                                   "wrapV": ts.get("m_WrapV", 0), "mips": int(tt.get("m_MipCount", 1)) > 1}
        return name

    def material(self, pptr):
        r = V.deref(pptr)
        if r is None:
            return ""
        tt = r.read_typetree()
        name = tt["m_Name"]
        if name in self.materials:
            return name
        sh = V.deref(tt.get("m_Shader"))
        shader = None
        if sh is not None:
            st = sh.read_typetree()
            shader = st.get("m_ParsedForm", {}).get("m_Name") or st.get("m_Name")
        props = tt.get("m_SavedProperties", {})
        texs = []
        for pn, te in props.get("m_TexEnvs", []):
            t = V.deref(te.get("m_Texture"))
            if t is None or t.type.name != "Texture2D":
                continue
            texs.append({"prop": pn, "tex": self.texture(t), "scale": [te["m_Scale"]["x"], te["m_Scale"]["y"]],
                         "offset": [te["m_Offset"]["x"], te["m_Offset"]["y"]]})
        self.materials[name] = {
            "name": name, "shader": shader or "",
            "keywords": list(tt.get("m_ValidKeywords") or []) or (tt.get("m_ShaderKeywords") or "").split(),
            "renderQueue": int(tt.get("m_CustomRenderQueue", -1)),
            "textures": texs,
            "floats": [{"name": k, "value": float(v)} for k, v in props.get("m_Floats", [])],
            "colors": [{"name": k, "rgba": [float(v[c]) for c in "rgba"]} for k, v in props.get("m_Colors", [])],
        }
        return name

    def mesh(self, pptr):
        r = V.deref(pptr)
        if r is None:
            return ""
        name = r.read_typetree()["m_Name"]
        if name not in self.meshes:
            p = self.out / "mesh" / f"{name}.obj"
            if not p.exists():
                p.write_text(r.read().export(), encoding="utf-8")
            self.meshes[name] = {"file": f"mesh/{name}.obj"}
        return name

    # ---------------------------------------------------------------- nodes
    def ps(self, tt, ps_index):
        im = tt["InitialModule"]
        em = tt["EmissionModule"]
        sh = tt["ShapeModule"]
        n = {
            "duration": float(tt["lengthInSec"]), "looping": bool(tt["looping"]), "prewarm": bool(tt["prewarm"]),
            "startDelay": mmc(tt["startDelay"]), "simulationSpeed": float(tt.get("simulationSpeed", 1.0)),
            "simSpace": int(tt.get("moveWithTransform", 0)), "scalingMode": int(tt.get("scalingMode", 1)),
            "lifetime": mmc(im["startLifetime"]), "speed": mmc(im["startSpeed"]), "startColor": mmg(im["startColor"]),
            "size3D": bool(im.get("size3D", False)), "sizeX": mmc(im["startSize"]), "sizeY": mmc(im["startSizeY"]),
            "sizeZ": mmc(im["startSizeZ"]), "rotation3D": bool(im.get("rotation3D", False)),
            "rotX": mmc(im["startRotationX"]), "rotY": mmc(im["startRotationY"]), "rotZ": mmc(im["startRotation"]),
            "flipRotation": float(im.get("randomizeRotationDirection", 0.0)), "gravity": mmc(im["gravityModifier"]),
            "maxParticles": int(im.get("maxNumParticles", 1000)),
            "emission": {"enabled": bool(em["enabled"]), "rate": mmc(em["rateOverTime"]), "rateDist": mmc(em["rateOverDistance"]),
                         "bursts": [{"time": float(b["time"]), "count": mmc(b["countCurve"]), "cycles": int(b.get("cycleCount", 1)),
                                     "interval": float(b.get("repeatInterval", 0.01)), "probability": float(b.get("probability", 1.0))}
                                    for b in em.get("m_Bursts", [])]},
            "shape": {"enabled": bool(sh["enabled"]), "type": int(sh["type"]), "angle": float(sh["angle"]),
                      "length": float(sh["length"]), "radius": float(sh["radius"]["value"]),
                      "radiusThickness": float(sh["radiusThickness"]), "arc": float(sh["arc"]["value"]),
                      "arcMode": int(sh["arc"]["mode"]), "boxThickness": v3(sh["boxThickness"]),
                      "position": v3(sh["m_Position"]), "rotation": v3(sh["m_Rotation"]), "scale": v3(sh["m_Scale"]),
                      "donutRadius": float(sh["donutRadius"]), "randomDirection": float(sh["randomDirectionAmount"]),
                      "sphericalDirection": float(sh["sphericalDirectionAmount"]),
                      "randomPosition": float(sh["randomPositionAmount"]), "alignToDirection": bool(sh["alignToDirection"]),
                      "mesh": self.mesh(sh.get("m_Mesh")) if sh["type"] in (6, 13, 14) else "",
                      "meshSpawnMode": int(sh["m_MeshSpawn"]["mode"])},
        }
        c = tt["ColorModule"]
        n["color"] = {"enabled": bool(c["enabled"]), "gradient": mmg(c["gradient"])}
        s = tt["SizeModule"]
        n["size"] = {"enabled": bool(s["enabled"]), "separate": bool(s["separateAxes"]), "x": mmc(s["curve"]), "y": mmc(s["y"]), "z": mmc(s["z"])}
        r = tt["RotationModule"]
        n["rotation"] = {"enabled": bool(r["enabled"]), "separate": bool(r["separateAxes"]), "x": mmc(r["x"]), "y": mmc(r["y"]), "z": mmc(r["curve"])}
        v = tt["VelocityModule"]
        n["velocity"] = {"enabled": bool(v["enabled"]), "x": mmc(v["x"]), "y": mmc(v["y"]), "z": mmc(v["z"]),
                         "orbitalX": mmc(v["orbitalX"]), "orbitalY": mmc(v["orbitalY"]), "orbitalZ": mmc(v["orbitalZ"]),
                         "radial": mmc(v["radial"]), "speedModifier": mmc(v["speedModifier"]), "world": bool(v["inWorldSpace"])}
        f = tt["ForceModule"]
        n["force"] = {"enabled": bool(f["enabled"]), "x": mmc(f["x"]), "y": mmc(f["y"]), "z": mmc(f["z"]), "world": bool(f["inWorldSpace"])}
        cl = tt["ClampVelocityModule"]
        n["limit"] = {"enabled": bool(cl["enabled"]), "separate": bool(cl["separateAxis"]), "x": mmc(cl["x"]), "y": mmc(cl["y"]),
                      "z": mmc(cl["z"]), "magnitude": mmc(cl["magnitude"]), "dampen": float(cl["dampen"]), "drag": mmc(cl["drag"]),
                      "dragBySize": bool(cl["multiplyDragByParticleSize"]), "dragByVelocity": bool(cl["multiplyDragByParticleVelocity"]),
                      "world": bool(cl["inWorldSpace"])}
        no = tt["NoiseModule"]
        n["noise"] = {"enabled": bool(no["enabled"]), "separate": bool(no["separateAxes"]), "x": mmc(no["strength"]),
                      "y": mmc(no["strengthY"]), "z": mmc(no["strengthZ"]), "frequency": float(no["frequency"]),
                      "damping": bool(no["damping"]), "octaves": int(no["octaves"]), "octaveMultiplier": float(no["octaveMultiplier"]),
                      "octaveScale": float(no["octaveScale"]), "quality": int(no["quality"]), "scrollSpeed": mmc(no["scrollSpeed"]),
                      "positionAmount": mmc(no["positionAmount"]), "rotationAmount": mmc(no["rotationAmount"]),
                      "sizeAmount": mmc(no["sizeAmount"])}
        uv = tt["UVModule"]
        n["uv"] = {"enabled": bool(uv["enabled"]), "mode": int(uv["mode"]), "timeMode": int(uv.get("timeMode", 0)),
                   "fps": float(uv.get("fps", 30.0)), "frameOverTime": mmc(uv["frameOverTime"]), "startFrame": mmc(uv["startFrame"]),
                   "tilesX": int(uv["tilesX"]), "tilesY": int(uv["tilesY"]), "animationType": int(uv["animationType"]),
                   "rowIndex": int(uv["rowIndex"]), "cycles": float(uv["cycles"]), "rowMode": int(uv.get("rowMode", 1))}
        tr = tt["TrailModule"]
        n["trail"] = {"enabled": bool(tr["enabled"]), "mode": int(tr["mode"]), "ratio": float(tr["ratio"]), "lifetime": mmc(tr["lifetime"]),
                      "minVertexDistance": float(tr["minVertexDistance"]), "textureMode": int(tr["textureMode"]),
                      "world": bool(tr["worldSpace"]), "dieWithParticles": bool(tr["dieWithParticles"]),
                      "sizeAffectsWidth": bool(tr["sizeAffectsWidth"]), "sizeAffectsLifetime": bool(tr["sizeAffectsLifetime"]),
                      "inheritParticleColor": bool(tr["inheritParticleColor"]), "colorOverLifetime": mmg(tr["colorOverLifetime"]),
                      "widthOverTrail": mmc(tr["widthOverTrail"]), "colorOverTrail": mmg(tr["colorOverTrail"]),
                      "ribbonCount": int(tr.get("ribbonCount", 1))}
        lm = tt["LightsModule"]
        tmpl = V.deref(lm.get("light"))
        light = None
        if tmpl is not None:
            lt = tmpl.read_typetree()
            light = {"type": int(lt["m_Type"]), "color": [float(lt["m_Color"][c]) for c in "rgba"],
                     "intensity": float(lt["m_Intensity"]), "range": float(lt["m_Range"])}
        n["lights"] = {"enabled": bool(lm["enabled"]), "ratio": float(lm["ratio"]), "random": bool(lm["randomDistribution"]),
                       "useColor": bool(lm["color"]), "useRange": bool(lm["range"]), "useIntensity": bool(lm["intensity"]),
                       "rangeCurve": mmc(lm["rangeCurve"]), "intensityCurve": mmc(lm["intensityCurve"]),
                       "maxLights": int(lm["maxLights"]), "template": light or {"type": 2, "color": [1, 1, 1, 1], "intensity": 1, "range": 1},
                       "sizeAffectsRange": bool(lm.get("sizeAffectsRange", True)), "alphaAffectsIntensity": bool(lm.get("alphaAffectsIntensity", True))}
        sub = tt["SubModule"]
        n["sub"] = {"enabled": bool(sub["enabled"]),
                    "emitters": [{"psPathId": int(e["emitter"]["m_PathID"]), "type": int(e["type"]), "properties": int(e["properties"]),
                                  "probability": float(e.get("emitProbability", 1.0))} for e in sub.get("subEmitters", [])
                                 if e["emitter"]["m_PathID"]]}
        cd = tt["CustomDataModule"]
        n["custom"] = {"enabled": bool(cd["enabled"]), "mode0": int(cd["mode0"]), "count0": int(cd["vectorComponentCount0"]),
                       "v0": [mmc(cd[f"vector0_{i}"]) for i in range(4)], "color0": mmg(cd["color0"]),
                       "mode1": int(cd["mode1"]), "count1": int(cd["vectorComponentCount1"]),
                       "v1": [mmc(cd[f"vector1_{i}"]) for i in range(4)], "color1": mmg(cd["color1"])}
        n["unsupportedModules"] = [m for m in MODULE_KEYS if tt.get(m, {}).get("enabled") and m not in SUPPORTED]
        return n

    def renderer(self, tt):
        mats = [self.material(m) for m in tt.get("m_Materials", [])]
        return {"enabled": bool(tt.get("m_Enabled", 1)), "renderMode": int(tt["m_RenderMode"]),
                "material": mats[0] if mats else "", "trailMaterial": mats[1] if len(mats) > 1 else "",
                "lengthScale": float(tt["m_LengthScale"]), "velocityScale": float(tt["m_VelocityScale"]),
                "cameraVelocityScale": float(tt["m_CameraVelocityScale"]), "sortingFudge": float(tt["m_SortingFudge"]),
                "sortMode": int(tt["m_SortMode"]), "sortingOrder": int(tt.get("m_SortingOrder", 0)),
                "minParticleSize": float(tt["m_MinParticleSize"]), "maxParticleSize": float(tt["m_MaxParticleSize"]),
                "alignment": int(tt["m_RenderAlignment"]), "pivot": v3(tt["m_Pivot"]), "flip": v3(tt.get("m_Flip", {"x": 0, "y": 0, "z": 0})),
                "mesh": self.mesh(tt.get("m_Mesh")) if int(tt["m_RenderMode"]) == 4 else "",
                "allowRoll": bool(tt.get("m_AllowRoll", True)), "normalDirection": float(tt.get("m_NormalDirection", 1.0))}

    def walk(self, go_reader, parent, nodes, root=False):
        go = go_reader.read_typetree()
        if not go.get("m_IsActive", True) and not root:
            return
        node = {"name": go["m_Name"], "parent": parent, "pos": [0, 0, 0], "rot": [0, 0, 0, 1], "scale": [1, 1, 1],
                "hasPS": False, "psPathId": 0}
        children = []
        for c in go["m_Component"]:
            cr = V.deref(c["component"])
            if cr is None:
                continue
            tn = cr.type.name
            if tn not in ("Transform", "ParticleSystem", "ParticleSystemRenderer", "SkinnedMeshRenderer", "MeshRenderer"):
                continue
            tt = cr.read_typetree()
            if tn == "Transform":
                node["pos"] = v3(tt["m_LocalPosition"])
                q = tt["m_LocalRotation"]
                node["rot"] = [float(q["x"]), float(q["y"]), float(q["z"]), float(q["w"])]
                node["scale"] = v3(tt["m_LocalScale"])
                children = tt["m_Children"]
            elif tn == "ParticleSystem":
                node["ps"] = self.ps(tt, len(nodes))
                node["hasPS"] = True
                node["psPathId"] = cr.path_id
            elif tn == "ParticleSystemRenderer":
                node["renderer"] = self.renderer(tt)
            else:   # a mesh renderer's materials, for bodyOverlay lab replicas (appended to the unit's body)
                node["meshMaterials"] = [self.material(m) for m in tt.get("m_Materials", [])]
        idx = len(nodes)
        nodes.append(node)
        for ch in children:
            tr = V.deref(ch)
            if tr is not None:
                self.walk(V.deref(tr.read_typetree()["m_GameObject"]), idx, nodes)


def find_child(go_reader, name):
    go = go_reader.read_typetree()
    for c in go["m_Component"]:
        cr = V.deref(c["component"])
        if cr is not None and cr.type.name == "Transform":
            for ch in cr.read_typetree()["m_Children"]:
                cgo = V.deref(V.deref(ch).read_typetree()["m_GameObject"])
                if cgo.read_typetree()["m_Name"] == name:
                    return cgo
                hit = find_child(cgo, name)
                if hit is not None:
                    return hit
    return None


def find_direct_child(go_reader, name):
    """Resolve a qualified source path one Transform edge at a time; repeated names below another branch cannot win."""
    go = go_reader.read_typetree()
    hits = []
    for c in go["m_Component"]:
        cr = V.deref(c["component"])
        if cr is not None and cr.type.name == "Transform":
            for ch in cr.read_typetree()["m_Children"]:
                cgo = V.deref(V.deref(ch).read_typetree()["m_GameObject"])
                if cgo.read_typetree()["m_Name"] == name:
                    hits.append(cgo)
    if len(hits) > 1:
        raise SystemExit(f"FAIL: ambiguous direct child {name!r} under {go['m_Name']!r}")
    return hits[0] if hits else None


def extract(out: Path, spec: str, ex: Extractor):
    path, _, sub = spec.partition(":")
    _, cont = V.env()
    ptrs = V.lookup(cont, path)
    go = next(V.resources_file().objects[p["m_PathID"]] for p in ptrs
              if V.resources_file().objects.get(p["m_PathID"]) is not None
              and V.resources_file().objects[p["m_PathID"]].type.name == "GameObject")
    parts = [s for s in sub.split("/") if s]
    for part in parts:
        nxt = find_direct_child(go, part) if len(parts) > 1 else find_child(go, part)
        if nxt is None:
            raise SystemExit(f"FAIL: node {part} not under {path}")
        go = nxt
    nodes = []
    ex.walk(go, -1, nodes, root=True)
    parent_name = ""
    for c in go.read_typetree()["m_Component"]:
        cr = V.deref(c["component"])
        if cr is not None and cr.type.name == "Transform":
            ptr = V.deref(cr.read_typetree()["m_Father"])
            if ptr is not None:
                parent_name = V.deref(ptr.read_typetree()["m_GameObject"]).read_typetree()["m_Name"]
    ps_index = {n["psPathId"]: i for i, n in enumerate(nodes) if n["hasPS"]}
    for n in nodes:
        if n.get("ps"):
            for e in n["ps"]["sub"]["emitters"]:
                e["node"] = ps_index.get(e["psPathId"], -1)
    return {"source": spec, "parentName": parent_name, "nodes": nodes}


def main():
    out = Path(sys.argv[1])
    ex = Extractor(out)
    recipes = {}
    for spec in sys.argv[2:]:
        key = recipe_key(spec)
        if key in recipes and recipes[key]["source"] != spec:
            raise SystemExit(f"FAIL: recipe key collision {key}: {recipes[key]['source']} vs {spec}")
        r = extract(out, spec, ex)
        recipes[key] = r
        (out / f"{key}.json").write_text(json.dumps(r, indent=1), encoding="utf-8")
        unsup = sorted({m for n in r["nodes"] if n.get("ps") for m in n["ps"]["unsupportedModules"]})
        shaders = sorted({ex.materials[n["renderer"]["material"]]["shader"] for n in r["nodes"]
                          if n.get("renderer") and n["renderer"]["material"]})
        print(f"{spec}: {len(r['nodes'])} nodes, shaders {shaders}, unsupported modules {unsup}")
    (out / "materials.json").write_text(json.dumps({"materials": list(ex.materials.values()),
                                                    "textures": ex.textures, "meshes": ex.meshes}, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
