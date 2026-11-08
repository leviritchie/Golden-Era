#!/usr/bin/env python3
"""Mesh surgery (no Meshy spend): cut a Meshy town building's baked-in ground plate.

    python tools/homm3_town_scene_meshes/cut_ground_plate.py tbelcstl_2 --below 0.035

Meshy sometimes returns a building standing on a full-footprint slab (tbelcstl_2 a1: the bottom 3% of its
height spans the whole 1.90 x 1.90 xz box while the walls above span 1.48). Registered on the town plate,
that slab reads as a pale platform around the fort. This drops every face whose vertices all lie below
`--below` x height from the bottom; faces that cross the cut (wall bases) are kept, so the body is untouched.
Output: <MESHY>/<name>_noplate/mesh_a1/ with the source textures and a surgery.json provenance record; the
preview STATE/VARIANT_STATES entry then names that mesh. Proof tier: generated artifact.
"""
from __future__ import annotations

import argparse
import json
import shutil
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_conflux_town3d_preview as B  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name")
    ap.add_argument("--below", type=float, required=True, help="cut height as a fraction of the mesh height")
    a = ap.parse_args()
    src = B.MESHY / a.name / B.MESH_ATTEMPT
    dst = B.MESHY / f"{a.name}_noplate" / B.MESH_ATTEMPT
    # Edit the GLB in place at the glTF level: only each primitive's index list shrinks (unreferenced vertices
    # stay), so everything else - materials, embedded images, samplers - is Meshy's bytes. (A trimesh re-export
    # was rejected by the glTFast importer.)
    raw = (src / "model.glb").read_bytes()
    jlen = struct.unpack_from("<I", raw, 12)[0]
    gj = json.loads(raw[20:20 + jlen])
    bin_off = 20 + jlen + 8
    binbuf = bytearray(raw[bin_off:bin_off + struct.unpack_from("<I", raw, 20 + jlen)[0]])
    if any(n.get("matrix") or n.get("rotation") or n.get("scale") or n.get("translation") for n in gj["nodes"]):
        raise SystemExit(f"{a.name}: node transforms present; this cut reads POSITION as world space")

    def view(acc_i: int, dtype, comps: int) -> tuple[np.ndarray, int]:
        acc = gj["accessors"][acc_i]
        bv = gj["bufferViews"][acc["bufferView"]]
        off = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
        arr = np.frombuffer(bytes(binbuf[off:off + acc["count"] * comps * np.dtype(dtype).itemsize]), dtype)
        return arr.reshape(-1, comps) if comps > 1 else arr, off

    prims = [pr for m in gj["meshes"] for pr in m["primitives"]]
    ys = np.concatenate([view(pr["attributes"]["POSITION"], np.float32, 3)[0][:, 1] for pr in prims])
    lo, hi = float(ys.min()), float(ys.max())
    cut = lo + a.below * (hi - lo)
    rep = {"source": str(src / "model.glb"), "belowFrac": a.below, "cutY": cut, "heightY": hi - lo, "primitives": []}
    idx_dtypes = {5121: np.uint8, 5123: np.uint16, 5125: np.uint32}
    for pr in prims:
        y = view(pr["attributes"]["POSITION"], np.float32, 3)[0][:, 1]
        acc = gj["accessors"][pr["indices"]]
        dt = idx_dtypes[acc["componentType"]]
        idx, off = view(pr["indices"], dt, 1)
        tri = idx.reshape(-1, 3)
        keep = ~(y[tri] < cut).all(1)
        if not keep.any():
            raise SystemExit(f"{a.name}: cut at {a.below} removes a whole primitive")
        kept = tri[keep].reshape(-1)
        # Compact the vertex attributes to the vertices still referenced (in place, each view shrinks), so the
        # plate's vertices leave the bounds and POSITION min/max the fitter and importers read.
        used = np.unique(kept)
        remap = np.full(len(y), -1, np.int64)
        remap[used] = np.arange(len(used))
        comps = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
        for att_i in pr["attributes"].values():
            att = gj["accessors"][att_i]
            bv = gj["bufferViews"][att["bufferView"]]
            if att["componentType"] != 5126:
                raise SystemExit(f"{a.name}: non-float attribute accessor {att_i}")
            nc = comps[att["type"]]
            if bv.get("byteStride", nc * 4) != nc * 4:
                raise SystemExit(f"{a.name}: interleaved attribute accessor {att_i}")
            arr, aoff = view(att_i, np.float32, nc)
            sub = np.ascontiguousarray(arr.reshape(-1, nc)[used]).astype(np.float32)
            binbuf[aoff:aoff + sub.nbytes] = sub.tobytes()
            att["count"] = int(len(used))
            bv["byteLength"] = int(sub.nbytes)
            if "min" in att or "max" in att:
                att["min"], att["max"] = sub.min(0).tolist(), sub.max(0).tolist()
        new_idx = remap[kept].astype(dt).tobytes()
        binbuf[off:off + len(new_idx)] = new_idx
        acc["count"] = int(keep.sum() * 3)
        gj["bufferViews"][acc["bufferView"]]["byteLength"] = len(new_idx)
        rep["primitives"].append({"trianglesBefore": int(len(tri)), "trianglesAfter": int(keep.sum()),
                                  "verticesBefore": int(len(y)), "verticesAfter": int(len(used))})
    jb = json.dumps(gj, separators=(",", ":")).encode()
    jb += b" " * (-len(jb) % 4)
    out = (struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(jb) + 8 + len(binbuf))
           + struct.pack("<II", len(jb), 0x4E4F534A) + jb + struct.pack("<II", len(binbuf), 0x004E4942) + bytes(binbuf))
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "model.glb").write_bytes(out)
    for f in src.glob("texture_0_*.png"):
        shutil.copy2(f, dst / f.name)
    v, _ = B.load_glb_unity(dst / "model.glb")
    lo_v, hi_v = v.min(0), v.max(0)
    h = hi_v[1] - lo_v[1]
    band = v[v[:, 1] < lo_v[1] + 0.03 * h]
    rep["result"] = {"extentXZ": (hi_v - lo_v)[[0, 2]].round(3).tolist(),
                     "bottom3pctExtentXZ": (band.max(0) - band.min(0))[[0, 2]].round(3).tolist()}
    (dst.parent / "surgery.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps(rep, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
