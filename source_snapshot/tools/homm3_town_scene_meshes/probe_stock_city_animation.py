#!/usr/bin/env python3
"""Probe how the stock Olden Era city scene animates its buildings and ambience (UnityPy, read-only).

    python tools/homm3_town_scene_meshes/probe_stock_city_animation.py [--level level67]

Writes artifacts/homm3_conflux_town3d/stock_city_animation_probe.json:
  * animators: full hierarchy path, controller, clips, and the transform paths/attributes each clip
    animates (what moves: rotation of blades, flags, doors, whole-body loops, ...)
  * particleSystems: path, main-module timing/size/speed, emission rate, shape, renderer mode and
    material/shader + the VfxUber-style material properties that drive the look
  * animatedMaterials: materials on scene renderers whose shader parameters move by themselves
    (Hex/Lit _UvScroll, emission blink, Hex/Sea, VfxUber scrolling noise)
Proof tier: static-asset (serialized scene read from the installed game files; no runtime).
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

import UnityPy

GAME = Path(r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/HeroesOldenEra_Data")
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts" / "homm3_conflux_town3d" / "stock_city_animation_probe.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", default="level67")
    a = ap.parse_args()
    idx = a.level.replace("level", "")
    env = UnityPy.load(str(GAME / a.level), str(GAME / f"sharedassets{idx}.assets"),
                       str(GAME / "globalgamemanagers.assets"), str(GAME / "resources.assets"))
    objs = {o.path_id: o for o in env.objects if o.assets_file.name == a.level}
    tfs = {}
    for o in objs.values():
        if o.type.name == "Transform":
            t = o.read()
            tfs[t.m_GameObject.path_id] = t

    name_cache: dict[int, str] = {}

    def goname(gid: int) -> str:
        if gid not in name_cache:
            try:
                name_cache[gid] = objs[gid].read().m_Name
            except Exception:
                name_cache[gid] = "?"
        return name_cache[gid]

    def path_of(gid: int) -> str:
        parts = []
        t = tfs.get(gid)
        while t is not None:
            parts.append(goname(t.m_GameObject.path_id))
            fa = t.m_Father
            t = fa.read() if fa.path_id else None
        return "/".join(reversed(parts))

    pid_to_gid = {o_.path_id: o_.read().m_GameObject.path_id for o_ in objs.values() if o_.type.name == "Transform"}
    kids = collections.defaultdict(list)
    for g_, t_ in tfs.items():
        if t_.m_Father.path_id:
            kids[pid_to_gid.get(t_.m_Father.path_id)].append(g_)

    def rel_paths(root_gid: int) -> dict:
        """crc32 of every transform path relative to an Animator's GameObject -> readable path."""
        import zlib

        out = {zlib.crc32(b"") & 0xFFFFFFFF: "(root)"}
        stack = [(root_gid, "")]
        while stack:
            g, pth = stack.pop()
            for k in kids.get(g, []):
                kp = f"{pth}/{goname(k)}" if pth else goname(k)
                out[zlib.crc32(kp.encode("utf-8")) & 0xFFFFFFFF] = kp
                stack.append((k, kp))
        return out

    def safe(fn, default=None):
        try:
            return fn()
        except Exception:
            return default

    animators, particles, mats_seen = [], [], {}
    for o in objs.values():
        if o.type.name == "Animator":
            an = o.read()
            gid = an.m_GameObject.path_id
            row = {"path": path_of(gid), "controller": None, "clips": []}
            ctrl = safe(lambda: an.m_Controller.read())
            if ctrl is not None:
                row["controller"] = getattr(ctrl, "m_Name", None)
                rel = rel_paths(gid)
                if hasattr(ctrl, "m_AnimationClips"):
                    crefs = list(ctrl.m_AnimationClips)
                else:  # AnimatorOverrideController: the override clips are what plays
                    crefs = [c.m_OverrideClip for c in ctrl.m_Clips if c.m_OverrideClip.path_id] +                             [c.m_OriginalClip for c in ctrl.m_Clips if not c.m_OverrideClip.path_id]
                    row["override"] = True
                for cref in crefs:
                    clip = safe(lambda: cref.read())
                    if clip is None:
                        continue
                    tt = safe(lambda: clip.object_reader.read_typetree(), {}) or {}
                    moved = collections.Counter()
                    attr = {1: "position", 2: "rotation", 3: "scale", 4: "euler"}
                    for g in (tt.get("m_ClipBindingConstant", {}) or {}).get("genericBindings", []) or []:
                        tgt = rel.get(g["path"], f"#{g['path']}")
                        kind = attr.get(g["attribute"], str(g["attribute"])) if g.get("typeID") == 4 else                             f"type{g.get('typeID')}.attr{g['attribute']}"
                        moved[(tgt, kind)] += 1
                    mc = tt.get("m_MuscleClip", {})
                    row["clips"].append({
                        "name": tt.get("m_Name"),
                        "length": safe(lambda: float(mc["m_StopTime"]) - float(mc["m_StartTime"])),
                        "loop": safe(lambda: bool(mc["m_LoopTime"])),
                        "animated": sorted(f"{k[0]} :: {k[1]}" for k in moved)[:40],
                        "bindingCount": sum(moved.values()),
                    })
            animators.append(row)
        elif o.type.name == "ParticleSystem":
            tt = o.read_typetree()
            gid = tt["m_GameObject"]["m_PathID"]
            init = tt.get("InitialModule", {})
            emis = tt.get("EmissionModule", {})
            shape = tt.get("ShapeModule", {})

            def mm(d):
                return safe(lambda: {"min": d.get("minScalar"), "scalar": d.get("scalar"), "mode": d.get("minMaxState")})

            particles.append({
                "path": path_of(gid),
                "duration": tt.get("lengthInSec"), "looping": tt.get("looping"),
                "simulationSpeed": tt.get("simulationSpeed"),
                "startLifetime": mm(init.get("startLifetime", {})), "startSpeed": mm(init.get("startSpeed", {})),
                "startSize": mm(init.get("startSize", {})), "maxParticles": init.get("maxNumParticles"),
                "gravity": mm(init.get("gravityModifier", {})),
                "rateOverTime": mm(emis.get("rateOverTime", {})), "bursts": len(emis.get("m_Bursts", []) or []),
                "shapeType": shape.get("type"), "shapeRadius": shape.get("radius", {}).get("value")
                if isinstance(shape.get("radius"), dict) else shape.get("radius"),
                "noise": bool(tt.get("NoiseModule", {}).get("enabled")),
                "uvSheet": bool(tt.get("UVModule", {}).get("enabled")),
                "lights": bool(tt.get("LightsModule", {}).get("enabled")),
                "trail": bool(tt.get("TrailModule", {}).get("enabled")),
            })
        elif o.type.name == "ParticleSystemRenderer":
            tt = o.read_typetree()
            gid = tt["m_GameObject"]["m_PathID"]
            mats = []
            for m in tt.get("m_Materials", []):
                mo = safe(lambda: env.assets[0] and None)
                mats.append(m)
            particles.append({"rendererFor": path_of(gid), "renderMode": tt.get("m_RenderMode"),
                              "materials": mats})
        elif o.type.name in ("MeshRenderer", "SkinnedMeshRenderer", "ParticleSystemRenderer"):
            pass

    # Resolve renderer materials (scene renderers + particle renderers) and flag self-animating params.
    for o in objs.values():
        if o.type.name not in ("MeshRenderer", "SkinnedMeshRenderer", "ParticleSystemRenderer"):
            continue
        r = o.read()
        gid = r.m_GameObject.path_id
        for mref in r.m_Materials:
            m = safe(lambda: mref.read())
            if m is None:
                continue
            key = m.m_Name
            if key in mats_seen:
                mats_seen[key]["users"].append(path_of(gid))
                continue
            shader = safe(lambda: m.m_Shader.read().m_ParsedForm.m_Name, None) or \
                safe(lambda: m.m_Shader.read().m_Name, "?")
            props = m.m_SavedProperties
            floats = {k: v for k, v in (safe(lambda: [(p[0], p[1]) for p in props.m_Floats], []) or [])}
            colors = {k: [round(v.r, 3), round(v.g, 3), round(v.b, 3), round(v.a, 3)]
                      for k, v in (safe(lambda: [(p[0], p[1]) for p in props.m_Colors], []) or [])}
            texs = {k: safe(lambda: v.m_Texture.read().m_Name) for k, v in
                    (safe(lambda: [(p[0], p[1]) for p in props.m_TexEnvs], []) or [])}
            kw = safe(lambda: list(m.m_ValidKeywords) + list(m.m_InvalidKeywords), None) or \
                safe(lambda: m.m_ShaderKeywords.split(), [])
            moving = {k: v for k, v in floats.items()
                      if any(s in k.lower() for s in ("speed", "scroll", "blink", "wave", "wind", "flow"))
                      and v not in (0, 0.0)}
            moving.update({k: v for k, v in colors.items() if "scroll" in k.lower() or "speed" in k.lower()})
            mats_seen[key] = {"shader": shader, "renderer": o.type.name, "keywords": kw, "moving": moving,
                              "hdrColors": {k: v for k, v in colors.items() if max(v[:3]) > 1.0},
                              "textures": {k: v for k, v in texs.items() if v}, "users": [path_of(gid)]}
    animated = {k: v for k, v in mats_seen.items()
                if v["moving"] or v["renderer"] == "ParticleSystemRenderer" or "Sea" in str(v["shader"])
                or any("EMISSION" in str(x) for x in v["keywords"])}
    for v in animated.values():
        v["userCount"] = len(v["users"])
        v["users"] = v["users"][:6]
    out = {"schema": "stock_city_animation_probe.v1", "level": a.level, "proof": "static-asset",
           "counts": {"animators": len(animators), "particleSystems": sum(1 for p in particles if "path" in p),
                      "animatedMaterials": len(animated)},
           "animators": animators, "particles": particles, "animatedMaterials": animated}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(json.dumps(out["counts"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
