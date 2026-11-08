#!/usr/bin/env python3
"""Bind a Meshy retexture's maps onto a unit's own source mesh, leaving its geometry bytes untouched.

  python tools/homm3_meshy_frame_pose/bind_retexture_maps.py <unit> <retexture.glb> [--write]

The retexture was made with `enable_original_uv` (retexture_unit_source_mesh.py), so its maps index the
source mesh's own TEXCOORD_0. This rewrites only the material / textures / images / samplers of
artifacts/meshy_downloads/<unit>_smartrigged.glb: every geometry, skin and animation bufferView is copied
byte for byte. The body's UV set sha (source_mesh_identity.uv_set_sha256) is checked before and after.
Base colour, metallic-roughness and normal are bound; the retexture's emission map is dropped (the unit
look stage owns glow). Every primitive gets the one material (the seaman mesh had none at all).

Without --write it reports only. With --write the previous file moves to
artifacts/meshy_downloads/_superseded_do_not_use/<unit>_smartrigged.<sha12>.glb (source_mesh_identity
refuses a build stamped from there), and the provenance JSON gains a `retexture` record.
A changed source sha means the unit needs a full run_unit.sh build (source_mesh_identity.REBUILD).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/homm3_def_retarget_delivery"))
import source_mesh_identity as SMI  # noqa: E402

MESHY = ROOT / "artifacts/meshy_downloads"
SUPERSEDED = MESHY / "_superseded_do_not_use"


def read(path: Path) -> tuple[dict, bytes]:
    b = path.read_bytes()
    if b[:4] != b"glTF":
        raise SystemExit(f"{path} is not a GLB")
    jl = struct.unpack_from("<I", b, 12)[0]
    js = json.loads(b[20:20 + jl])
    bl = struct.unpack_from("<I", b, 20 + jl)[0]
    return js, b[28 + jl:28 + jl + bl]


def view_bytes(js: dict, binb: bytes, i: int) -> bytes:
    bv = js["bufferViews"][i]
    o = bv.get("byteOffset", 0)
    return binb[o:o + bv["byteLength"]]


def write_glb(js: dict, binb: bytes) -> bytes:
    j = json.dumps(js, separators=(",", ":")).encode("utf-8")
    j += b" " * (-len(j) % 4)
    binb += b"\0" * (-len(binb) % 4)
    return (struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(j) + 8 + len(binb))
            + struct.pack("<II", len(j), 0x4E4F534A) + j + struct.pack("<II", len(binb), 0x004E4942) + binb)


def bind(target: Path, retex: Path) -> tuple[bytes, dict]:
    tj, tb = read(target)
    rj, rb = read(retex)
    if len(rj.get("materials", [])) != 1:
        raise SystemExit("retexture GLB must carry exactly one material")
    rm = rj["materials"][0]
    pbr = rm.get("pbrMetallicRoughness", {})
    slots = {"baseColor": pbr.get("baseColorTexture"), "metallicRoughness": pbr.get("metallicRoughnessTexture"),
             "normal": rm.get("normalTexture")}
    if not slots["baseColor"]:
        raise SystemExit("retexture material has no baseColorTexture")
    uv_before = SMI.uv_set_sha256(tj, tb)

    image_views = {im["bufferView"] for im in tj.get("images", []) if "bufferView" in im}
    out_views, remap, out_bin = [], {}, bytearray()
    for i, bv in enumerate(tj.get("bufferViews", [])):
        if i in image_views:
            continue
        out_bin += b"\0" * (-len(out_bin) % 4)
        nb = {k: v for k, v in bv.items() if k not in ("byteOffset", "buffer")}
        nb.update(buffer=0, byteOffset=len(out_bin))
        remap[i] = len(out_views)
        out_views.append(nb)
        out_bin += view_bytes(tj, tb, i)
    for a in tj.get("accessors", []):
        if "bufferView" in a:
            a["bufferView"] = remap[a["bufferView"]]
        sp = a.get("sparse")
        if sp:
            sp["indices"]["bufferView"] = remap[sp["indices"]["bufferView"]]
            sp["values"]["bufferView"] = remap[sp["values"]["bufferView"]]

    images, textures, mat = [], [], {"name": "Material_0", "doubleSided": True, "pbrMetallicRoughness": {}}
    for slot, ref in slots.items():
        if not ref:
            continue
        rimg = rj["images"][rj["textures"][ref["index"]]["source"]]
        data = view_bytes(rj, rb, rimg["bufferView"])
        out_bin += b"\0" * (-len(out_bin) % 4)
        out_views.append({"buffer": 0, "byteOffset": len(out_bin), "byteLength": len(data)})
        out_bin += data
        images.append({"name": f"retexture_{slot}", "mimeType": rimg.get("mimeType", "image/jpeg"),
                       "bufferView": len(out_views) - 1})
        textures.append({"sampler": 0, "source": len(images) - 1})
        t = {"index": len(textures) - 1}
        if slot == "baseColor":
            mat["pbrMetallicRoughness"]["baseColorTexture"] = t
        elif slot == "metallicRoughness":
            mat["pbrMetallicRoughness"]["metallicRoughnessTexture"] = t
        else:
            mat["normalTexture"] = t
    tj["bufferViews"] = out_views
    tj["buffers"] = [{"byteLength": len(out_bin)}]
    tj["images"], tj["textures"] = images, textures
    tj["samplers"] = [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}]
    tj["materials"] = [mat]
    for m in tj.get("meshes", []):
        for p in m["primitives"]:
            p["material"] = 0
    out = write_glb(tj, bytes(out_bin))
    nj, nb = read_bytes(out)
    uv_after = SMI.uv_set_sha256(nj, nb)
    if uv_after != uv_before:
        raise SystemExit(f"UV set changed {uv_before[:12]} -> {uv_after[:12]}: refusing")
    return out, {"uvSetSha256": uv_after, "boundMaps": list(k for k, v in slots.items() if v)}


def read_bytes(b: bytes) -> tuple[dict, bytes]:
    jl = struct.unpack_from("<I", b, 12)[0]
    bl = struct.unpack_from("<I", b, 20 + jl)[0]
    return json.loads(b[20:20 + jl]), b[28 + jl:28 + jl + bl]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("unit")
    ap.add_argument("retexture", type=Path)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    target = MESHY / f"{a.unit}_smartrigged.glb"
    old = target.read_bytes()
    out, rec = bind(target, a.retexture)
    old_sha, new_sha = hashlib.sha256(old).hexdigest(), hashlib.sha256(out).hexdigest()
    rec.update(unit=a.unit, previousSha256=old_sha, sha256=new_sha,
               retextureGlb=a.retexture.resolve().relative_to(ROOT).as_posix(),
               retextureGlbSha256=hashlib.sha256(a.retexture.read_bytes()).hexdigest())
    meta = a.retexture.parent / "retexture_meta.json"
    if meta.is_file():
        m = json.loads(meta.read_text(encoding="utf-8"))
        rec.update(taskId=m.get("taskId"), prompt=m.get("prompt"), consumedCredits=m.get("consumedCredits"))
    print(json.dumps(rec, indent=1))
    if not a.write:
        return 0
    SUPERSEDED.mkdir(parents=True, exist_ok=True)
    keep = SUPERSEDED / f"{a.unit}_smartrigged.{old_sha[:12]}.glb"
    if not keep.exists():
        shutil.copy2(target, keep)
    tmp = target.with_suffix(".glb.tmp")
    tmp.write_bytes(out)
    tmp.replace(target)
    prov = MESHY / f"{a.unit}_smartrigged.provenance.json"
    p = json.loads(prov.read_text(encoding="utf-8")) if prov.is_file() else {"unit": a.unit}
    rec["superseded"] = keep.relative_to(ROOT).as_posix()
    rec["proof"] = "generated artifact: maps bound offline, geometry bytes unchanged; needs a full run_unit.sh build"
    p["retexture"] = rec
    prov.write_text(json.dumps(p, indent=1), encoding="utf-8")
    print("WROTE", target.relative_to(ROOT).as_posix(), new_sha[:12], "superseded ->", keep.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
