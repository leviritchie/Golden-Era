#!/usr/bin/env python3
"""Export a stock Olden Era city scene (default cityHuman2 = level67) for the Unity town preview.

    python tools/homm3_town_scene_meshes/export_stock_city_scene.py [--level level67] [--out DIR]

Reads the installed scene with UnityPy (read-only) and writes:
  scene.json      camera / lights / fog / ambient + every visible renderer instance (world matrix,
                  mesh file, material textures, shader name)
  meshes/*.bin    int32 vcount, int32 subCount, float32 xyz*v, float32 nrm*v, float32 uv*v,
                  per submesh: int32 count + int32 indices
  tex/*.png       material _MainTex (Hex/Lit base colour), terrain splat colour
Stock starting-town state: only the building variants that the live ledger shows active at a new
Castle town (Main_Level_1, Tier_1_Level_1, Tier_2_Level_1) are kept; other BhBuilding variants
are skipped. Skinned renderers are exported in bind pose. Proof tier: generated artifact.
"""
from __future__ import annotations

import argparse
import json
import os
import struct
from pathlib import Path

import numpy as np
import UnityPy
from UnityPy.helpers.MeshHelper import MeshHandler

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/HeroesOldenEra_Data")
KEEP = {"H_build_Main_Level_1", "H_build_Tier_1_Level_1", "H_build_Tier_2_Level_1"}
MANAGER = "human_city_all_objects"


def trs(t) -> np.ndarray:
    p, q, s = t.m_LocalPosition, t.m_LocalRotation, t.m_LocalScale
    x, y, z, w = q.x, q.y, q.z, q.w
    r = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])
    m = np.eye(4)
    m[:3, :3] = r * np.array([s.x, s.y, s.z])
    m[:3, 3] = [p.x, p.y, p.z]
    return m


class Exporter:
    def __init__(self, level: str, out: Path):
        self.out = out
        (out / "meshes").mkdir(parents=True, exist_ok=True)
        (out / "tex").mkdir(parents=True, exist_ok=True)
        idx = level.replace("level", "")
        env = UnityPy.load(str(DATA / level), str(DATA / f"sharedassets{idx}.assets"),
                           str(DATA / "globalgamemanagers.assets"), str(DATA / "resources.assets"))
        self.objs = {o.path_id: o for o in env.objects if o.assets_file.name == level}
        self.meshes: dict[int, str] = {}
        self.textures: dict[tuple, str] = {}
        self.failed: list[dict] = []

    def comp(self, go, type_name):
        for c in go.m_Components:
            ref = getattr(c, "component", c)
            o = self.objs.get(ref.path_id)
            if o is not None and o.type.name == type_name:
                return o.read()
        return None

    def world(self, t):
        m = trs(t)
        g = t.m_GameObject.read()
        names, active = [g.m_Name], bool(g.m_IsActive)
        cur = t
        while cur.m_Father.path_id:
            cur = cur.m_Father.read()
            m = trs(cur) @ m
            g = cur.m_GameObject.read()
            names.append(g.m_Name)
            active = active and bool(g.m_IsActive)
        return m, "/".join(reversed(names)), active

    def write_mesh(self, name, v, n, uv, subs):
        with open(self.out / name, "wb") as f:
            f.write(struct.pack("<ii", len(v), len(subs)))
            f.write(np.asarray(v, np.float32).tobytes())
            f.write(np.asarray(n, np.float32).tobytes())
            f.write(np.asarray(uv, np.float32).tobytes())
            for s in subs:
                s = np.asarray(s, np.int32).reshape(-1)
                f.write(struct.pack("<i", len(s)))
                f.write(s.tobytes())

    @staticmethod
    def channel(data, count, dims, default):
        arr = np.array(data if data else [], np.float32).reshape(-1)
        for width in (dims, dims + 1, 4):
            if count and arr.size == count * width:
                return arr.reshape(count, width)[:, :dims]
        return np.tile(np.array(default, np.float32), (count, 1))

    def export_mesh(self, ref) -> str:
        if ref.path_id in self.meshes:
            return self.meshes[ref.path_id]
        h = MeshHandler(ref.read())
        h.process()
        v = np.array(h.m_Vertices, np.float32).reshape(-1, 3)
        n = self.channel(h.m_Normals, len(v), 3, (0.0, 1.0, 0.0))
        uv = self.channel(h.m_UV0, len(v), 2, (0.0, 0.0))
        name = f"meshes/{ref.path_id}.bin"
        self.write_mesh(name, v, n, uv, h.get_triangles())
        self.meshes[ref.path_id] = name
        return name

    def export_material(self, ref) -> dict:
        info = {"tex": None, "clip": False, "name": None, "shader": None}
        if not ref.path_id:
            return info
        try:
            mat = ref.read()
            info["name"] = mat.m_Name
            try:
                info["shader"] = mat.m_Shader.read().m_ParsedForm.m_Name
            except Exception:
                info["shader"] = "?"
            kws = getattr(mat, "m_ValidKeywords", None) or str(getattr(mat, "m_ShaderKeywords", ""))
            info["clip"] = "HEX_ALPHA_CLIP_ENABLED" in kws
            envs = {(k if isinstance(k, str) else k.name): v for k, v in mat.m_SavedProperties.m_TexEnvs}
            te = envs.get("_MainTex") or envs.get("_BaseMap")
            if te is None or not te.m_Texture.path_id:
                return info
            key = (te.m_Texture.file_id, te.m_Texture.path_id)
            if key not in self.textures:
                tex = te.m_Texture.read()
                img = tex.image
                if max(img.size) > 1024:
                    img = img.resize((img.width // 2, img.height // 2))
                fn = f"tex/{tex.m_Name}_{te.m_Texture.path_id}.png"
                img.save(self.out / fn)
                self.textures[key] = fn
            info["tex"] = self.textures[key]
        except Exception as exc:  # recorded per material, never silently substituted
            info["error"] = str(exc)[:120]
        return info

    def run(self) -> dict:
        instances, skipped = [], 0
        for o in self.objs.values():
            if o.type.name not in ("MeshRenderer", "SkinnedMeshRenderer"):
                continue
            r = o.read()
            if not r.m_Enabled:
                continue
            go = r.m_GameObject.read()
            m, path, active = self.world(self.comp(go, "Transform"))
            parts = path.split("/")
            if not active or (MANAGER in parts and not KEEP.intersection(parts)):
                skipped += 1
                continue
            if o.type.name == "MeshRenderer":
                mf = self.comp(go, "MeshFilter")
                mref = mf.m_Mesh if mf is not None else None
            else:
                mref = r.m_Mesh
            if mref is None or not mref.path_id:
                continue
            try:
                mesh_file = self.export_mesh(mref)
            except ValueError as exc:  # unreadable vertex stream: recorded, not substituted
                self.failed.append({"path": path, "error": str(exc)[:120]})
                continue
            mats = [self.export_material(x) for x in r.m_Materials]
            if all(x["shader"] == "magic/VfxUber" for x in mats):
                continue
            instances.append({"path": path, "mesh": mesh_file,
                              "skinned": o.type.name == "SkinnedMeshRenderer",
                              "m": [float(x) for x in m.T.reshape(-1)], "mats": mats})
        instances += self.terrain()
        camera, lights = None, []
        for o in self.objs.values():
            if o.type.name == "Camera":
                c = o.read_typetree()
                go = o.read().m_GameObject.read()
                m, path, _ = self.world(self.comp(go, "Transform"))
                camera = {"path": path, "m": [float(x) for x in m.T.reshape(-1)], "fov": c["field of view"],
                          "near": c["near clip plane"], "far": c["far clip plane"]}
            elif o.type.name == "Light":
                light = o.read()
                go = light.m_GameObject.read()
                m, path, active = self.world(self.comp(go, "Transform"))
                lights.append({"name": go.m_Name, "type": int(light.m_Type), "intensity": float(light.m_Intensity),
                               "color": [light.m_Color.r, light.m_Color.g, light.m_Color.b],
                               "range": float(getattr(light, "m_Range", 10.0)), "active": active,
                               "m": [float(x) for x in m.T.reshape(-1)]})
        rs = next(o.read_typetree() for o in self.objs.values() if o.type.name == "RenderSettings")
        col = lambda c: [c["r"], c["g"], c["b"]]  # noqa: E731
        scene = {"schema": "stock_city_export.v1", "camera": camera, "lights": lights, "instances": instances,
                 "fog": {"color": col(rs["m_FogColor"]), "start": rs["m_LinearFogStart"], "end": rs["m_LinearFogEnd"]},
                 "ambient": {"sky": col(rs["m_AmbientSkyColor"]), "equator": col(rs["m_AmbientEquatorColor"]),
                             "ground": col(rs["m_AmbientGroundColor"])},
                 "failedMeshes": self.failed,
                 "counts": {"failed": len(self.failed), "instances": len(instances), "skipped": skipped, "meshes": len(self.meshes),
                            "textures": len(self.textures)}}
        (self.out / "scene.json").write_text(json.dumps(scene, indent=1), encoding="utf-8")
        return scene["counts"]

    def terrain(self) -> list:
        from PIL import Image

        out = []
        for o in self.objs.values():
            if o.type.name != "Terrain":
                continue
            t = o.read()
            go = t.m_GameObject.read()
            m, path, _ = self.world(self.comp(go, "Transform"))
            td = t.m_TerrainData.read()
            tt = t.m_TerrainData.read_typetree()
            hm = tt["m_Heightmap"]
            res, sc = hm["m_Resolution"], hm["m_Scale"]
            heights = np.array(hm["m_Heights"], np.float32).reshape(res, res) / 32766.0 * sc["y"]
            cols, alpha = [], None
            try:
                # Resize each weight channel on its own: PIL premultiplies RGBA by A when resampling,
                # and the splat's A channel is a near-zero layer weight, which zeroed the whole map.
                aimg = td.m_SplatDatabase.m_AlphaTextures[0].read().image.convert("RGBA")
                alpha = np.stack([np.asarray(ch.resize((res, res)), np.float32) for ch in aimg.split()], -1) / 255.0
                for lref in td.m_SplatDatabase.m_TerrainLayers:
                    layer = lref.read()
                    img = layer.m_DiffuseTexture.read().image.convert("RGB").resize((64, 64))
                    cols.append(np.asarray(img, np.float32).reshape(-1, 3).mean(0) / 255.0)
            except Exception as exc:
                print("terrain splat unresolved:", exc)
                alpha = None
            step = 2
            idx = list(range(0, res, step))
            n = len(idx)
            v = np.array([(xi * sc["x"], heights[zi, xi], zi * sc["z"]) for zi in idx for xi in idx], np.float32)
            uv = np.array([(xi / (res - 1), zi / (res - 1)) for zi in idx for xi in idx], np.float32)
            f = []
            for zi in range(n - 1):
                for xi in range(n - 1):
                    a = zi * n + xi
                    f += [a, a + n, a + 1, a + 1, a + n, a + n + 1]
            self.write_mesh("meshes/terrain.bin", v, np.tile([0, 1, 0], (len(v), 1)), uv, [f])
            tex = None
            if alpha is not None and cols:
                c = sum(alpha[..., i:i + 1] * cols[i] for i in range(min(4, len(cols))))
                print("terrain splat: alpha means", alpha.reshape(-1, 4).mean(0).round(3).tolist(),
                      "layer colours", [x.round(3).tolist() for x in cols])
                Image.fromarray((np.clip(c, 0, 1) * 255).astype(np.uint8)).save(self.out / "tex/terrain_splat.png")
                tex = "tex/terrain_splat.png"
            out.append({"path": path, "mesh": "meshes/terrain.bin", "skinned": False, "recalcNormals": True,
                        "m": [float(x) for x in m.T.reshape(-1)],
                        "mats": [{"tex": tex, "clip": False, "name": "terrain", "shader": "terrain"}]})
        return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--level", default="level67")
    ap.add_argument("--out", type=Path, default=ROOT / "artifacts/homm3_conflux_town3d/stock_cityHuman2_export")
    a = ap.parse_args()
    os.environ.setdefault("PYTHONUTF8", "1")
    print(json.dumps(Exporter(a.level, a.out).run()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
