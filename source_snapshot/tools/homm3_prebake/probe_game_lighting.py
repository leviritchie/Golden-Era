#!/usr/bin/env python3
"""Read the installed game's scene lights, RenderSettings ambient and the Hex/Lit shader shape.

Read-only UnityPy scan of the active Golden Era install. It does not modify game files.
Writes ``artifacts/homm3_prebaked_lighting/game_lighting_probe.json``.

Proof tier: source/static (serialized scene data); it does not prove what a battle
frame actually renders, because runtime code may add, move or recolour lights.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import UnityPy

ROOT = Path(__file__).resolve().parents[2]
GAME = Path(r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/HeroesOldenEra_Data")
OUT = ROOT / "artifacts/homm3_prebaked_lighting/game_lighting_probe.json"


def quat_forward(q):
    # Unity: forward = rotation * (0,0,1); light shines along forward.
    x, y, z, w = q
    fx = 2 * (x * z + w * y)
    fy = 2 * (y * z - w * x)
    fz = 1 - 2 * (x * x + y * y)
    return [fx, fy, fz]


def colour(c):
    return [round(float(getattr(c, k)), 4) for k in ("r", "g", "b", "a")]


def scene_names() -> list[str]:
    env = UnityPy.load(str(GAME / "globalgamemanagers"))
    for obj in env.objects:
        if obj.type.name == "BuildSettings":
            data = obj.read()
            return list(getattr(data, "scenes", []) or [])
    return []


def scan(path: Path, names: list[str]) -> dict:
    env = UnityPy.load(str(path))
    lights, render, shaders = [], [], []
    for obj in env.objects:
        t = obj.type.name
        if t == "Light":
            d = obj.read()
            go = d.m_GameObject.read() if d.m_GameObject else None
            fwd = None
            if go is not None:
                for comp in go.m_Component:
                    c = comp.component.read() if hasattr(comp, "component") else comp.read()
                    if c.object_reader.type.name == "Transform":
                        r = c.m_LocalRotation
                        fwd = quat_forward((r.x, r.y, r.z, r.w))
                        # parent chain rotation is ignored; record parent presence
                        break
            lights.append({
                "gameObject": getattr(go, "m_Name", None),
                "active": getattr(go, "m_IsActive", None),
                "enabled": bool(getattr(d, "m_Enabled", True)),
                "type": int(d.m_Type), "color": colour(d.m_Color),
                "intensity": float(d.m_Intensity),
                "shadows": int(getattr(d.m_Shadows, "m_Type", -1)) if hasattr(d, "m_Shadows") else None,
                "localForward": [round(v, 4) for v in fwd] if fwd else None,
            })
        elif t == "RenderSettings":
            d = obj.read()
            render.append({
                "ambientMode": int(getattr(d, "m_AmbientMode", -1)),
                "ambientSky": colour(d.m_AmbientSkyColor), "ambientEquator": colour(d.m_AmbientEquatorColor),
                "ambientGround": colour(d.m_AmbientGroundColor),
                "ambientIntensity": float(getattr(d, "m_AmbientIntensity", -1)),
                "subtractiveShadow": colour(d.m_SubtractiveShadowColor) if hasattr(d, "m_SubtractiveShadowColor") else None,
            })
        elif t == "Shader":
            try:
                d = obj.read()
                parsed = getattr(d, "m_ParsedForm", None)
                name = parsed.m_Name if parsed is not None else getattr(d, "m_Name", "")
                if name and name.startswith("Hex/"):
                    info = {"name": name}
                    if parsed is not None:
                        info["properties"] = [p.m_Name for p in parsed.m_PropInfo.m_Props]
                        passes = []
                        for sub in parsed.m_SubShaders:
                            for p in sub.m_Passes:
                                tags = {}
                                try:
                                    tags = {k: v for k, v in p.m_Tags.tags}
                                except Exception:
                                    pass
                                passes.append({"name": getattr(p.m_State, "m_Name", ""), "tags": tags})
                        info["passes"] = passes
                        try:
                            info["keywords"] = sorted(set(parsed.m_KeywordNames))[:400]
                        except Exception:
                            pass
                    shaders.append(info)
            except Exception as exc:  # noqa: BLE001 - diagnostic scan
                shaders.append({"error": repr(exc)[:200]})
    return {"lights": lights, "renderSettings": render, "hexShaders": shaders}


def main() -> int:
    names = []
    try:
        names = scene_names()
    except Exception as exc:  # noqa: BLE001
        print("build settings unreadable:", exc)
    files = sorted(GAME.glob("level*"), key=lambda p: int(p.name[5:]) if p.name[5:].isdigit() else 999)
    files += sorted(GAME.glob("sharedassets*.assets"))
    files += [GAME / "resources.assets"]
    result = {"proof": "source/static serialized scene data", "game": str(GAME), "scenes": names, "files": {}}
    for f in files:
        if not f.is_file():
            continue
        try:
            r = scan(f, names)
        except Exception as exc:  # noqa: BLE001
            r = {"error": repr(exc)[:300]}
        if r.get("lights") or r.get("renderSettings") or r.get("hexShaders") or r.get("error"):
            idx = f.name[5:] if f.name.startswith("level") else None
            if idx and idx.isdigit() and int(idx) < len(names):
                r["scene"] = names[int(idx)]
            result["files"][f.name] = r
            print(f.name, r.get("scene"), len(r.get("lights", [])), "lights",
                  len(r.get("hexShaders", [])), "hex shaders", r.get("error", ""), flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
