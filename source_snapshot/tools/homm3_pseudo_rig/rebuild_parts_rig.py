#!/usr/bin/env python3
"""
Rebuild the crusader part-rig mesh from the DENSE Meshy-7 segmentation GLB.

Why this exists: the previous decimation (target ~200 faces per part, from ~212K
per part) produced a triangle soup with zero edge connectivity (every triangle its
own 3-vertex island). Free LBS over that mesh cannot produce anything but a spiky
shredded blob. This script:

  1. Loads `crusader_part_segmentation.glb` (15 watertight part shells, vertex
     colors = part ids, KHR_mesh_quantization local positions).
  2. Dequantizes positions (node scale/trans) into world units.
  3. Quadric-decimates each part independently (connectivity-preserving) with a
     per-part face budget (big parts keep more faces).
  4. Welds the seams: merges vertices across parts within `weld_eps` (the dense
     seams are coincident), producing ONE watertight mesh.
  5. Recomputes per-vertex part ids + seam influence weights (Gaussian in
     nearest-other-part distance) and writes the part-rig npz + json.

Outputs (overwrite):
  artifacts/crusader_pose_pipeline/pseudo_rig/parts_rig/crusader_parts_rig.npz
  artifacts/crusader_pose_pipeline/pseudo_rig/parts_rig/crusader_parts_rig.json

Also writes a debug GLB of the welded mesh for visual inspection.

Proof label: generated-artifact (host mesh rebuild) — not OE runtime.
"""
from __future__ import annotations

import argparse
import json
import struct
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SEG_GLB = Path(r"C:\Users\<user>\Downloads\crusader_part_segmentation.glb")
OUT_DIR = ROOT / "artifacts/crusader_pose_pipeline/pseudo_rig/parts_rig"


# ---------------------------------------------------------------- GLB parsing

def parse_glb(path: Path):
    data = path.read_bytes()
    off = 12
    json_data = bin_data = None
    while off < len(data):
        l, t = struct.unpack("<I4s", data[off:off + 8])
        ch = data[off + 8:off + 8 + l]
        if t == b"JSON":
            json_data = json.loads(ch.decode("utf-8"))
        elif t == b"BIN\x00":
            bin_data = ch
        off += 8 + l
    assert json_data is not None and bin_data is not None
    return json_data, bin_data


def read_acc(j, bin_data, idx):
    acc = j["accessors"][idx]
    bv = j["bufferViews"][acc["bufferView"]]
    byte_off = int(bv.get("byteOffset", 0) + acc.get("byteOffset", 0))
    count = int(acc["count"])
    ctype = acc["componentType"]
    typ = acc["type"]
    dtype_map = {5126: np.float32, 5123: np.uint16, 5125: np.uint32, 5121: np.uint8}
    type_map = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
    dtype = dtype_map[ctype]
    nc = type_map[typ]
    stride = int(bv.get("byteStride", 0))
    if stride and stride > nc * np.dtype(dtype).itemsize:
        # strided (interleaved) buffer: gather per-row
        arr = np.empty((count, nc), dtype=dtype)
        for i in range(count):
            row = np.frombuffer(bin_data, dtype=dtype, count=nc,
                                offset=byte_off + i * stride)
            arr[i] = row
    else:
        arr = np.frombuffer(bin_data, dtype=dtype, count=count * nc, offset=byte_off)
        if nc > 1:
            arr = arr.reshape(count, nc)
    return arr


def dequantize_positions(j, bin_data, prim):
    """Decode KHR_mesh_quantization positions: ushort 0-65535 maps to accessor
    min/max (local space); world = local*S + T from the node matrix."""
    acc = j["accessors"][prim["attributes"]["POSITION"]]
    raw = read_acc(j, bin_data, prim["attributes"]["POSITION"])
    lo = np.array(acc["min"], dtype=np.float64)
    hi = np.array(acc["max"], dtype=np.float64)
    local = lo[None, :] + (raw.astype(np.float64) / 65535.0) * (hi - lo)[None, :]
    return local


# ---------------------------------------------------------------- weld helpers

def union_find(n):
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    return find, union


def read_acc_dequant(j, bin_data, idx):
    """Read a POSITION accessor from the Meshy segmentation GLB.

    This file's positions are KHR_mesh_quantization ushort with byteStride=8
    (3*ushort + 2 pad bytes) and accessor min/max holding RAW local bounds
    (non-compliant with the spec — the node matrix carries scale+translation
    into world space). We therefore decode as: world = raw_ushort*S + T,
    honoring the stride. Indices (no stride, no min/max) pass through.
    """
    acc = j["accessors"][idx]
    bv = j["bufferViews"][acc["bufferView"]]
    byte_off = int(bv.get("byteOffset", 0))
    count = int(acc["count"])
    ctype = acc["componentType"]
    typ = acc["type"]
    dtype_map = {5126: np.float32, 5123: np.uint16, 5125: np.uint32, 5121: np.uint8}
    type_map = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
    dtype = dtype_map[ctype]
    nc = type_map[typ]
    itemsize = np.dtype(dtype).itemsize
    stride = int(bv.get("byteStride", nc * itemsize))
    raw = np.frombuffer(bin_data, dtype=np.uint8, count=count * stride, offset=byte_off)
    raw = raw.reshape(count, stride)
    base = raw[:, :nc * itemsize].copy().view(dtype).reshape(count, nc)
    if ctype != 5126:
        base = base.astype(np.float64)
    return base


def weld_vertices(verts, part_ids, faces, eps):
    """Fuse Meshy auto-split parts into ONE watertight mesh.

    Meshy auto-split caps each part (closed shell for printing); adjacent caps
    are coincident double-wall geometry with small per-pair clearance gaps.
    We weld verts across parts ONLY where that part pair actually meets:
    per-pair threshold = pair min distance + margin, exact ball queries
    (no k-bound -> no chained pinch points). Interior caps collapse into
    shared seam verts; the rest stays put. Duplicate triangles are removed.

    Returns (verts, part_ids, faces, part_fracs): part_fracs is (N, n_parts)
    giving each welded vertex's share of contributing parts (interior 1.0,
    seam verts split).
    """
    from scipy.spatial import cKDTree
    t0 = time.perf_counter()
    n_parts = int(part_ids.max()) + 1
    n = len(verts)
    trees = {}
    for p in range(n_parts):
        sub = np.where(part_ids == p)[0]
        if len(sub):
            trees[p] = cKDTree(verts[sub])
    # ---- per-pair seam distance ----
    pair_min = {}
    for a in range(n_parts):
        if a not in trees:
            continue
        sub = np.where(part_ids == a)[0]
        for b in range(a + 1, n_parts):
            if b not in trees:
                continue
            d = trees[b].query(verts[sub], k=1)[0]
            pair_min[(a, b)] = float(d.min())
    # ---- weld edges per pair (exact ball queries, adaptive threshold) ----
    edges = []
    for (a, b), dmin in pair_min.items():
        if dmin > eps:
            continue
        thr = dmin + 0.005
        sa = np.where(part_ids == a)[0]
        sb = np.where(part_ids == b)[0]
        # verts of a within thr of b
        nbr_b = trees[b].query_ball_point(verts[sa], r=thr)
        for i, nbrs in enumerate(nbr_b):
            for j in nbrs:
                edges.append((int(sa[i]), int(sb[j])))
        nbr_a = trees[a].query_ball_point(verts[sb], r=thr)
        for i, nbrs in enumerate(nbr_a):
            for j in nbrs:
                edges.append((int(sb[i]), int(sa[j])))
    edges = np.array(edges, dtype=np.int64) if edges else np.zeros((0, 2), dtype=np.int64)
    edges = np.unique(np.sort(edges, axis=1), axis=0)
    n_pairs = len(edges)
    # ---- connected components over the weld edges (vectorized) ----
    import scipy.sparse as sp
    from scipy.sparse.csgraph import connected_components
    if n_pairs:
        spm = sp.coo_matrix((np.ones(n_pairs), (edges[:, 0], edges[:, 1])),
                            shape=(n, n)).tocsr()
        _, labels = connected_components(spm, directed=False)
    else:
        labels = np.arange(n)
    _, new_idx = np.unique(labels, return_inverse=True)
    n_new = int(new_idx.max()) + 1
    # averaged positions
    pos_acc = np.zeros((n_new, 3), dtype=np.float64)
    cnt = np.zeros(n_new, dtype=np.float64)
    np.add.at(pos_acc, new_idx, verts)
    np.add.at(cnt, new_idx, 1.0)
    verts_new = pos_acc / cnt[:, None]
    # part fraction per merged vert (cluster composition) + majority part id
    fracs = np.zeros((n_new, n_parts), dtype=np.float64)
    np.add.at(fracs, new_idx, np.eye(n_parts, dtype=np.float64)[part_ids])
    part_ids_new = fracs.argmax(axis=1).astype(np.int32)
    # remap faces
    faces_new = new_idx[faces]
    # drop exact-duplicate triangles (sorted vertex key)
    f_before = len(faces_new)
    keys = np.sort(faces_new, axis=1)
    _, uniq = np.unique(keys, axis=0, return_index=True)
    faces_new = faces_new[np.sort(uniq)]
    dt = time.perf_counter() - t0
    print(f"[weld] {n} -> {n_new} verts ({100.0*(n-n_new)/max(1,n):.1f}% merged) "
          f"cross-part pairs {n_pairs} tris {f_before} -> {len(faces_new)} "
          f"(dedup {f_before-len(faces_new)}) in {dt:.1f}s")
    return (verts_new.astype(np.float32), part_ids_new, faces_new.astype(np.int64),
            fracs.astype(np.float32))


# ---------------------------------------------------------------- main build

def build(target_faces: int = 60000, weld_eps: float = 0.004, sigma: float = 0.012,
          k: int = 3, agg: float = 4.0, min_part: int = 500, max_part: int = 9000,
          debug_glb: bool = True, weld_first: bool = True) -> dict:
    import fast_simplification as fs

    j, bin = parse_glb(SEG_GLB)
    nodes = j.get("nodes", [])
    meshes = j["meshes"]
    n_parts = len(meshes)

    # node matrix: all mesh nodes share scale S + trans T
    m = nodes[0].get("matrix")
    S = m[0]
    T = np.array([m[12], m[13], m[14]], dtype=np.float64)

    orig_counts = []
    part_verts = []
    part_faces = []
    for mi in range(n_parts):
        prim = meshes[mi]["primitives"][0]
        pos = read_acc_dequant(j, bin, prim["attributes"]["POSITION"])
        idx = read_acc_dequant(j, bin, prim["indices"]).astype(np.int64)
        v = pos * S + T
        f = idx.reshape(-1, 3)
        part_verts.append(v)
        part_faces.append(f)
        orig_counts.append(len(f))
    print(f"[load] {n_parts} parts, total faces {sum(orig_counts)}")

    # per-part decimation budgets
    ratio = target_faces / sum(orig_counts)
    budgets = [int(np.clip(c * ratio, min_part, max_part)) for c in orig_counts]
    total_budget = sum(budgets)
    print(f"[decimate] budgets {budgets} total {total_budget}")

    if weld_first:
        # ---- weld the DENSE mesh first: seams are exactly coincident there, so
        # the fusion is complete and watertight. Then decimate the fused mesh
        # (connectivity-preserving quadric collapse keeps the seams welded).
        verts0 = np.concatenate(part_verts, axis=0)
        faces0 = np.concatenate([f + off for f, off in zip(part_faces, np.cumsum([0] + [len(v) for v in part_verts]))], axis=0)
        pid0 = np.concatenate([np.full(len(part_verts[i]), i, dtype=np.int32) for i in range(n_parts)])
        vw, pw, fw, fracs_w = weld_vertices(verts0, pid0, faces0, weld_eps)
        t0 = time.perf_counter()
        v2, f2 = fs.simplify(vw, fw, target_count=total_budget, agg=agg)
        v2 = np.asarray(v2, dtype=np.float64)
        f2 = np.asarray(f2, dtype=np.int64)
        # part id + fractions per decimated vert: nearest original welded vert
        from scipy.spatial import cKDTree as _T
        tree = _T(vw)
        _, nn = tree.query(v2, k=1)
        part_ids = pw[nn]
        fracs = fracs_w[nn]
        verts = v2
        faces = f2
        print(f"[weld-first] dense {len(vw)}v/{len(fw)}f -> decimated {len(v2)}v/{len(f2)}f "
              f"({time.perf_counter()-t0:.1f}s)")
    else:
        dv = []
        df = []
        for mi in range(n_parts):
            v = part_verts[mi]
            f = part_faces[mi]
            b = budgets[mi]
            t0 = time.perf_counter()
            if len(f) <= b:
                v2, f2 = v, f
            else:
                v2, f2 = fs.simplify(v, f, target_count=b, agg=agg)
                v2 = np.asarray(v2, dtype=np.float64)
                f2 = np.asarray(f2, dtype=np.int64)
            dv.append(v2)
            df.append(f2)
            print(f"  part {mi:2d}: {len(f)} -> {len(f2)} faces ({time.perf_counter()-t0:.1f}s)")

        # concatenate
        offsets = np.cumsum([0] + [len(v) for v in dv])
        verts = np.concatenate(dv, axis=0)
        faces = np.concatenate([f + offsets[i] for i, f in enumerate(df)], axis=0)
        part_ids = np.concatenate([np.full(len(dv[i]), i, dtype=np.int32) for i in range(n_parts)])

        # weld seams
        verts, part_ids, faces = weld_vertices(verts, part_ids, faces, weld_eps)

    # ---- mesh health checks ----
    open_edges = 0
    e = {}
    for tri in faces:
        for kk in range(3):
            a, b = int(tri[kk]), int(tri[(kk + 1) % 3])
            key = (a, b) if a < b else (b, a)
            e[key] = e.get(key, 0) + 1
    open_edges = sum(1 for c in e.values() if c == 1)
    nonmanifold = sum(1 for c in e.values() if c > 2)
    print(f"[health] verts {len(verts)} faces {len(faces)} open_edges {open_edges} "
          f"nonmanifold_edges {nonmanifold} f/v {len(faces)/max(1,len(verts)):.2f} "
          f"unique-part-ids {len(np.unique(part_ids))}")
    # connected components: expect ONE (all parts fused at seams)
    adjv = {}
    for tri in faces[:200000]:
        for kk in range(3):
            a, b = int(tri[kk]), int(tri[(kk + 1) % 3])
            adjv.setdefault(a, set()).add(b)
            adjv.setdefault(b, set()).add(a)
    seen = set()
    comps = []
    for v0 in adjv:
        if v0 in seen:
            continue
        stack = [v0]; seen.add(v0); sz = 0
        while stack:
            vv = stack.pop(); sz += 1
            for nb in adjv.get(vv, ()):
                if nb not in seen:
                    seen.add(nb); stack.append(nb)
        comps.append(sz)
    print(f"[health] connected components (first 200k tris): {len(comps)} "
          f"largest {max(comps) if comps else 0}")

    # ---- normalize: center XY, scale height (y-range) to 1.0, keep y origin at rest ----
    vmin = verts.min(0)
    vmax = verts.max(0)
    height = vmax[1] - vmin[1]
    center_xy = np.array([(vmin[0] + vmax[0]) / 2.0, vmin[1], (vmin[2] + vmax[2]) / 2.0])
    verts_n = (verts - center_xy[None, :]) / height
    print(f"[norm] world bbox {vmin} {vmax} height {height:.4f}")

    centroids = np.array([verts_n[part_ids == p].mean(0) for p in range(n_parts)], dtype=np.float32)

    # ---- influence weights from weld-cluster composition ----
    # Every vertex's influence is the composition of the weld cluster it came
    # from: interior verts are 1.0 on one part; seam verts split across the
    # parts whose caps fused there. This is exact (no sigma tuning) and keeps
    # seams watertight under rigid part motion.
    t0 = time.perf_counter()
    # keep only the parts with nonzero share, top-K by share
    influence_parts = np.full((len(verts_n), k), -1, dtype=np.int32)
    influence_weights = np.zeros((len(verts_n), k), dtype=np.float32)
    for i in range(len(verts_n)):
        order = np.argsort(-fracs[i])
        nz = order[fracs[i][order] > 1e-6][:k]
        if len(nz) == 0:
            nz = order[:1]
        influence_parts[i, :len(nz)] = nz
        w = fracs[i][nz]
        influence_weights[i, :len(nz)] = w / w.sum()
    print(f"[influence] weld-cluster weights in {time.perf_counter()-t0:.1f}s")
    active = (influence_weights > 1e-6)
    seam = active.sum(1)
    print(f"[influence] verts with 1 part: {int((seam==1).sum())} "
          f"2: {int((seam==2).sum())} 3: {int((seam==3).sum())}")

    # ---- adjacency pairs: parts that share weld-cluster verts ----
    adj = []
    share = (fracs > 1e-6)
    for a in range(n_parts):
        for b in range(a + 1, n_parts):
            both = share[:, a] & share[:, b]
            if both.sum() > 0:
                # min distance between the two parts' dominant verts
                ia = np.where(share[:, a] & ~share[:, b])[0]
                ib = np.where(share[:, b] & ~share[:, a])[0]
                dmin = 0.0
                if len(ia) and len(ib):
                    from scipy.spatial import cKDTree as _T
                    dmin = float(_T(verts_n[ia]).query(verts_n[ib], k=1)[0].min())
                adj.append([int(a), int(b), round(max(dmin, 1e-6), 6)])
    print(f"[adjacency] {len(adj)} pairs: {adj}")

    # ---- write outputs ----
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    npz_path = OUT_DIR / "crusader_parts_rig.npz"
    np.savez_compressed(
        npz_path,
        verts=verts_n.astype(np.float32),
        faces=faces.astype(np.int32),
        part_ids=part_ids.astype(np.int32),
        influence_parts=influence_parts,
        influence_weights=influence_weights,
        centroids=centroids,
        world_bbox_min=vmin.astype(np.float64),
        world_height=np.float64(height),
        center_xy=center_xy.astype(np.float64),
    )
    meta = {
        "schema": "homm3_pseudo_rig_part_rig.v2",
        "unitSid": "h3_crusader",
        "source": str(SEG_GLB),
        "nVerts": len(verts_n),
        "nFaces": len(faces),
        "nParts": n_parts,
        "decimate": {"targetFaces": target_faces, "budgets": budgets, "agg": agg,
                     "weldFirst": weld_first},
        "weldEps": weld_eps,
        "blend": {"sigma": sigma, "K": k, "mode": "weld-cluster-composition",
                  "singlePartFrac": float((seam == 1).mean()),
                  "twoPartFrac": float((seam == 2).mean())},
        "adjacentPairs": adj,
        "worldTransform": {"scale": S, "trans": T.tolist(),
                           "centerXY": center_xy.tolist(), "height": float(height)},
        "proof": "generated-artifact — v2 host mesh rebuild (dense source, welded seams); not OE runtime",
    }
    (OUT_DIR / "crusader_parts_rig.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"[write] {npz_path}")

    if debug_glb:
        glb = write_debug_glb(verts_n, faces, part_ids)
        print(f"[write] debug glb {glb}")

    return meta


# ---------------------------------------------------------------- debug glb

def write_debug_glb(verts, faces, part_ids) -> Path:
    """Minimal GLB (positions + vertex colors = part id) for inspection."""
    n = len(verts)
    colors = np.zeros((n, 3), dtype=np.float32)
    pal = np.array([
        [1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 0], [1, 0, 1],
        [0, 1, 1], [0.5, 0, 0], [0, 0.5, 0], [0, 0, 0.5], [0.5, 0.5, 0],
        [0.5, 0, 0.5], [0, 0.5, 0.5], [0.8, 0.8, 0.2], [0.2, 0.8, 0.8], [0.8, 0.2, 0.8],
    ], dtype=np.float32)
    colors[:] = pal[part_ids]
    idx = faces.astype(np.uint32)
    bin_parts = [
        verts.astype(np.float32).tobytes(),
        colors.tobytes(),
        idx.tobytes(),
    ]
    bin_data = b"".join(bin_parts)
    offs = []
    o = 0
    for b in bin_parts:
        offs.append(o)
        o += len(b)
    gltf = {
        "asset": {"generator": "crusader-parts-debug", "version": "2.0"},
        "buffers": [{"byteLength": len(bin_data)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": offs[0], "byteLength": len(bin_parts[0])},
            {"buffer": 0, "byteOffset": offs[1], "byteLength": len(bin_parts[1])},
            {"buffer": 0, "byteOffset": offs[2], "byteLength": len(bin_parts[2])},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": n, "type": "VEC3",
             "min": verts.min(0).astype(float).tolist(), "max": verts.max(0).astype(float).tolist()},
            {"bufferView": 1, "componentType": 5126, "count": n, "type": "VEC3"},
            {"bufferView": 2, "componentType": 5125, "count": len(idx), "type": "SCALAR"},
        ],
        "meshes": [{"primitives": [{
            "attributes": {"POSITION": 0, "COLOR_0": 1}, "indices": 2,
        }]}],
        "nodes": [{"mesh": 0, "name": "welded_crusader"}],
        "scenes": [{"nodes": [0]}], "scene": 0,
    }
    js = json.dumps(gltf).encode("utf-8")
    pad = lambda b: b + b"\x00" * ((4 - len(b) % 4) % 4)  # noqa: E731
    js = pad(js)
    bin_data = pad(bin_data)
    total = 12 + 8 + len(js) + 8 + len(bin_data)
    out = bytearray(struct.pack("<I4sI", total, b"glTF", 2))
    out += struct.pack("<I4s", len(js), b"JSON")
    out += js
    out += struct.pack("<I4s", len(bin_data), b"BIN\x00")
    out += bin_data
    p = OUT_DIR / "crusader_parts_welded_debug.glb"
    p.write_bytes(bytes(out))
    return p


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target-faces", type=int, default=60000)
    ap.add_argument("--weld-eps", type=float, default=0.004)
    ap.add_argument("--sigma", type=float, default=0.012)
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--agg", type=float, default=4.0)
    ap.add_argument("--min-part", type=int, default=500)
    ap.add_argument("--max-part", type=int, default=9000)
    ap.add_argument("--no-weld-first", action="store_true")
    ap.add_argument("--default-eps", type=float, default=0.065)
    args = ap.parse_args()
    meta = build(target_faces=args.target_faces, weld_eps=args.weld_eps,
                 sigma=args.sigma, k=args.k, agg=args.agg,
                 min_part=args.min_part, max_part=args.max_part,
                 weld_first=not args.no_weld_first)
    print(json.dumps(meta, indent=2))
