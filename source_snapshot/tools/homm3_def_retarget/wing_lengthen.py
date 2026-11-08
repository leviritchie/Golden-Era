"""Rest-pose wing surgery: lengthen a unit's wing geometry from the WingX_01 head (numpy, no Blender).

Why (authenticity pass, 2026-10-07, griffin line): the Meshy wings span only .75-.85 of the DEF width in the
spread frames (Defence/Hitted/Move) although the fitted chains are already straight at full reach; a 1.22 bone
scale on WingL/R_01 matched the DEF spreads, but as an animated op the patch lane's stretch gate refuses it (it
measures against rest geometry). So the rest mesh itself is lengthened and the unit is rebuilt (full chain).

Method: per `wings` block entry of the unit config, the wing vertices are the region box minus its excludes (the
same cut build_unit.py binds to the wing bone), in Blender coordinates (x, -z, y of the glTF). The chain is
recomputed exactly as ext/wing_chain.after_skin does (SVD axis from the head, 99th percentile far end, ratios);
every wing vertex is scaled about the WingX_01 head (ratio 1) by `scale`, ramped in smoothly over the chain
coordinate `ramp` (default 0.22-0.38) so the shoulder/arm segment and the body seam stay exactly in place.
Positions only; the Meshy UVs and topology are untouched. The same config-driven cut works for every unit of the
griffin line (royal, base folded mesh, battle).
Explicit chain (a folded wing, whose SVD axis is ambiguous): a `wingChain.wings[]` entry with "points" (the same
key ext/wing_chain.py builds the chain bones from) replaces the SVD chain for that bone: the chain coordinate is
the arc-length fraction of each vertex's nearest point on the polyline, and the vertices are scaled about
points[1] (2026-10-07 h3_griffin folded mesh: SVD far reach L .856 vs R .527; the head -> wrist -> tip polyline
is symmetric, wrist at arc .285 on both sides).

Usage: python wing_lengthen.py <unit config.json> <in.glb> <out.glb> [--scale 1.22] [--ramp 0.22 0.38]
Prints the new region extents: widen the config's wing region boxes so they still hold the lengthened wings.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

import numpy as np


def read_glb(p):
    b = Path(p).read_bytes()
    jl = struct.unpack_from("<I", b, 12)[0]
    js = json.loads(b[20:20 + jl])
    bl = struct.unpack_from("<I", b, 20 + jl)[0]
    return js, bytearray(b[28 + jl:28 + jl + bl])


def write_glb(p, js, binb):
    jb = json.dumps(js, separators=(",", ":")).encode()
    jb += b" " * (-len(jb) % 4)
    binb = bytes(binb) + b"\0" * (-len(binb) % 4)
    out = struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(jb) + 8 + len(binb))
    out += struct.pack("<II", len(jb), 0x4E4F534A) + jb + struct.pack("<II", len(binb), 0x004E4942) + binb
    Path(p).write_bytes(out)


def in_box(X, box):
    lo, hi = np.array(box[0]), np.array(box[1])
    return np.all((X >= lo) & (X <= hi), axis=1)


def near_segments(X, segs, radius):
    hit = np.zeros(len(X), bool)
    for a, b in segs:
        a, b = np.array(a, float), np.array(b, float)
        d = b - a
        t = np.clip(((X - a) @ d) / max(d @ d, 1e-12), 0, 1)
        hit |= np.linalg.norm(X - (a + t[:, None] * d), axis=1) <= radius
    return hit


def wing_rows(B, w):
    """the region cut (box minus excludes: boxes, or capsule `segments` + `radius`, as build_unit.make_owner)"""
    m = in_box(B, w["region"]["box"])
    for ex in w["region"].get("exclude", []):
        if "box" in ex:
            m &= ~in_box(B, ex["box"])
        elif "segments" in ex:
            m &= ~near_segments(B, ex["segments"], ex.get("radius", 0.05))
        else:
            raise SystemExit(f"unsupported exclude shape {sorted(ex)}")
    return np.nonzero(m)[0]


def chain(X, head, ratios):
    c = X.mean(0)
    _, _, Vt = np.linalg.svd(X - c, full_matrices=False)
    ax = Vt[0] if Vt[0] @ (c - head) > 0 else -Vt[0]
    far = np.percentile((X - head) @ ax, 99)
    return ax, far, np.array([head + ax * far * r for r in ratios])


def polyline_coord(X, pts):
    """arc-length fraction (0..1) of each row's nearest point on the polyline pts, and the polyline length"""
    seg = np.diff(pts, axis=0)
    sl = np.linalg.norm(seg, axis=1)
    cum = np.r_[0.0, np.cumsum(sl)]
    best_d, best_s = np.full(len(X), np.inf), np.zeros(len(X))
    for i, (a, d) in enumerate(zip(pts[:-1], seg)):
        u = np.clip(((X - a) @ d) / max(d @ d, 1e-12), 0, 1)
        dist = np.linalg.norm(X - (a + u[:, None] * d), axis=1)
        m = dist < best_d
        best_d[m], best_s[m] = dist[m], cum[i] + u[m] * sl[i]
    return best_s / cum[-1], float(cum[-1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cfg"); ap.add_argument("inp"); ap.add_argument("out")
    ap.add_argument("--scale", type=float, default=1.22)
    ap.add_argument("--ramp", type=float, nargs=2, default=[0.22, 0.38])
    a = ap.parse_args()
    cfg = json.load(open(a.cfg))
    wc = cfg.get("wingChain", {})
    ratios = wc.get("ratios", [0, 0.3, 0.55, 0.78, 1.0])
    explicit = {w["bone"]: np.array(w["points"], float) for w in wc.get("wings", []) if "points" in w}
    js, binb = read_glb(a.inp)
    report = {"schema": "homm3_def_retarget.wing_lengthen.v1", "input": a.inp,
              "inputSha256": hashlib.sha256(Path(a.inp).read_bytes()).hexdigest(),
              "scale": a.scale, "ramp": a.ramp, "wings": []}
    done = set()
    for m in js["meshes"]:
        for pr in m["primitives"]:
            ai = pr["attributes"]["POSITION"]
            if ai in done:
                continue
            done.add(ai)
            acc = js["accessors"][ai]
            bv = js["bufferViews"][acc["bufferView"]]
            off = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
            stride = bv.get("byteStride", 12)
            assert stride == 12 and acc["componentType"] == 5126, "tightly packed float32 positions expected"
            P = np.frombuffer(binb, np.float32, acc["count"] * 3, off).reshape(-1, 3).astype(np.float64)
            B = np.stack([P[:, 0], -P[:, 2], P[:, 1]], 1)          # glTF Y-up -> Blender Z-up
            for w in cfg["wings"]:
                rows = wing_rows(B, w)
                if len(rows) < 50:
                    continue
                head = np.array(w["head"], float)
                if w["bone"] in explicit:
                    pts = explicit[w["bone"]]
                    h1 = pts[1]
                    t, far = polyline_coord(B[rows], pts)
                    reach0 = float(np.percentile(np.linalg.norm(B[rows] - h1, axis=1), 99))
                else:
                    ax, far, pts = chain(B[rows], head, ratios)
                    h1 = pts[1]
                    t = ((B[rows] - head) @ ax) / far
                r0, r1 = a.ramp
                s = np.clip((t - r0) / (r1 - r0), 0, 1)
                s = s * s * (3 - 2 * s)
                B[rows] += (s * (a.scale - 1))[:, None] * (B[rows] - h1)
                if w["bone"] in explicit:     # the polyline length plus the hand's added reach past points[1]
                    far2 = far + float(np.percentile(np.linalg.norm(B[rows] - h1, axis=1), 99) - reach0)
                else:
                    ax2, far2, pts2 = chain(B[rows], head, ratios)
                rec = {"bone": w["bone"], "verts": int(len(rows)), "wing01Head": h1.round(4).tolist(),
                       "farBefore": round(float(far), 4), "farAfter": round(float(far2), 4),
                       "boxNeeded": [B[rows].min(0).round(3).tolist(), B[rows].max(0).round(3).tolist()],
                       "boxConfig": w["region"]["box"]}
                report["wings"].append(rec)
                print(json.dumps(rec))
            Pn = np.stack([B[:, 0], B[:, 2], -B[:, 1]], 1).astype(np.float32)
            binb[off:off + Pn.nbytes] = Pn.tobytes()
            acc["min"] = Pn.min(0).tolist(); acc["max"] = Pn.max(0).tolist()
    write_glb(a.out, js, binb)
    report["outputSha256"] = hashlib.sha256(Path(a.out).read_bytes()).hexdigest()
    Path(a.out).with_suffix(".surgery.json").write_text(json.dumps(report, indent=1) + "\n")
    print("WROTE", a.out, report["outputSha256"][:12])


if __name__ == "__main__":
    main()
