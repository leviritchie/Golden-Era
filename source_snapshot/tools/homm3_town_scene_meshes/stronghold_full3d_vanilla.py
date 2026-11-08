#!/usr/bin/env python3
"""Stronghold full-3D: read-only extract of the vanilla Olden Era desert assets used as filler (no Meshy).

    python tools/homm3_town_scene_meshes/stronghold_full3d_vanilla.py

UnityPy reads the installed Golden Era resources.assets (never written) and caches under
artifacts/homm3_stronghold_full3d/vanilla/:
  tex/<name>.png     terrain detail + rock albedo (Texture2D, by name + width, first match)
  mesh/<name>.npz    v (N,3) n (N,3) uv (N,2) f (M,3) in the asset's model space
  provenance.json    file, pathId, size, sha256 of every cached PNG / mesh npz
Rocks are the vanilla desert adventure-map rocks (Rock_desert_new_0x with their Dez_Rock_New_0x_diffuse, Des_Rock_0x
with des_rock_x_diffuse) and the cliff kit (Cliff2_Big / Cliff2_Small with Cliff_01_diffuse). The extracted assets are
not committed. Proof tier: generated artifact.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stronghold_full3d_common as SC  # noqa: E402

GAME_DATA = Path(r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/HeroesOldenEra_Data")
OUT = SC.DATA / "vanilla"
TEXTURES = SC.FP.VANILLA_TEXTURES   # name -> expected width
VFX = SC.FP.VANILLA_VFX             # name -> expected width; kept RGBA under vanilla/vfx/
MESHES = SC.FP.VANILLA_MESHES

def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def extract() -> dict:
    (OUT / "tex").mkdir(parents=True, exist_ok=True)
    (OUT / "mesh").mkdir(parents=True, exist_ok=True)
    (OUT / "vfx").mkdir(parents=True, exist_ok=True)
    prov_p = OUT / "provenance.json"
    prov = json.loads(prov_p.read_text(encoding="utf-8")) if prov_p.is_file() else {"tex": {}, "mesh": {}}
    prov.setdefault("vfx", {})
    want_v = {k: w for k, w in VFX.items() if k not in prov["vfx"] or not (OUT / "vfx" / f"{k}.png").is_file()}
    want_t = {k: w for k, w in TEXTURES.items() if k not in prov["tex"] or not (OUT / "tex" / f"{k}.png").is_file()}
    want_m = [m for m in MESHES if m not in prov["mesh"] or not (OUT / "mesh" / f"{m}.npz").is_file()]
    if want_t or want_m or want_v:
        import UnityPy
        from UnityPy.helpers.MeshHelper import MeshHandler
        env = UnityPy.load(str(GAME_DATA / "resources.assets"))
        for o in env.objects:
            if o.type.name == "Texture2D" and want_v:
                tt = o.read_typetree()
                nm = tt.get("m_Name")
                if nm in want_v and tt.get("m_Width") == want_v[nm]:
                    del want_v[nm]
                    o.read().image.convert("RGBA").save(OUT / "vfx" / f"{nm}.png")
                    prov["vfx"][nm] = {"file": "resources.assets", "pathId": int(o.path_id), "width": tt["m_Width"]}
                    continue
            if o.type.name == "Texture2D" and want_t:
                tt = o.read_typetree()
                nm = tt.get("m_Name")
                if nm in want_t and tt.get("m_Width") == want_t[nm]:
                    del want_t[nm]
                    p = OUT / "tex" / f"{nm}.png"
                    o.read().image.convert("RGB").save(p)
                    prov["tex"][nm] = {"file": "resources.assets", "pathId": int(o.path_id), "width": tt["m_Width"]}
            elif o.type.name == "Mesh" and want_m:
                tt = o.read_typetree()
                nm = tt.get("m_Name")
                if nm in want_m:
                    want_m.remove(nm)
                    h = MeshHandler(o.read())
                    h.process()
                    v = np.array(h.m_Vertices, np.float32).reshape(-1, 3)
                    nrm = np.array(h.m_Normals, np.float32).reshape(len(v), -1)[:, :3] if h.m_Normals else np.zeros_like(v)
                    uv = np.array(h.m_UV0, np.float32).reshape(len(v), -1)[:, :2] if h.m_UV0 else np.zeros((len(v), 2), np.float32)
                    f = np.concatenate([np.asarray(t, np.int32).reshape(-1, 3) for t in h.get_triangles()], 0)
                    p = OUT / "mesh" / f"{nm}.npz"
                    np.savez_compressed(p, v=v, n=nrm, uv=uv, f=f)
                    prov["mesh"][nm] = {"file": "resources.assets", "pathId": int(o.path_id), "verts": len(v),
                                        "tris": len(f)}
        if want_t or want_m or want_v:
            raise SystemExit(f"vanilla assets not found: textures {sorted(want_t)} vfx {sorted(want_v)} meshes {want_m}")
    for kind, ext in (("tex", "png"), ("mesh", "npz"), ("vfx", "png")):
        for nm, row in prov[kind].items():
            row["sha256"] = sha(OUT / kind / f"{nm}.{ext}")
    prov_p.write_text(json.dumps(prov, indent=1), encoding="utf-8")
    return prov


def tex(name: str) -> np.ndarray:
    from PIL import Image
    return np.asarray(Image.open(OUT / "tex" / f"{name}.png").convert("RGB"))


def mesh(name: str) -> dict:
    with np.load(OUT / "mesh" / f"{name}.npz") as d:
        return {k: d[k] for k in ("v", "n", "uv", "f")}


if __name__ == "__main__":
    p = extract()
    print(json.dumps({k: {n: {kk: vv for kk, vv in r.items() if kk != "sha256"} for n, r in v.items()} for k, v in p.items()}, indent=1))
