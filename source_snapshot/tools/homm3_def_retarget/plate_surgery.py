"""plate_surgery.py <src.glb> <out.glb> [--box x0,x1,y0,y1] [--zmin 0.15] [--back-y 0.30,0.58] [--dilate 3] [--preview out.png]

Texture surgery for h3_dwarf_battlerager (authenticity pass 2026-10-09, coordinator send-back 1): the Meshy mesh baked the
DEF battlerager's resting maul head into the skirt front as a grey, gold-studded plate. The front of the skirt there is
flat (the plate is painted, not modelled: front depth stays 0.26-0.28 from the belt to the hem), so the cut is a
re-paint of its texels with the skirt's own scale mail.

- Plate faces: front faces (centroid z > zmin, normal z > 0.2) inside the box whose texel at the UV centroid is grey
  (low saturation) or gold, grown one ring over faces in the box that are not scale-mail brown.
- Donor: the back of the same skirt (normal z < -0.3, z < 0), which is scale mail from the sash to the hem. A plate
  texel's surface point (x, y) maps to the back point (x, y') with y' the plate's y range squeezed into back-y, found
  as the back face under (x, y') in the xy plane; its barycentric UV gives the colour (bilinear).
- Only texels inside plate-face UV triangles (plus a `dilate`-texel gutter that no other face covers) are written;
  refuses when another face's UV triangle overlaps a written texel. Geometry, UVs and skin are byte-identical; only
  the base-colour image changes.
Writes <out>.surgery.json.
"""
import sys, io, json, hashlib, argparse, struct
from pathlib import Path
import numpy as np
from PIL import Image
from scipy.spatial import cKDTree

class glbio:   # minimal GLB reader/writer (single BIN chunk)
    CT = {5126: np.float32, 5125: np.uint32, 5123: np.uint16, 5121: np.uint8}
    NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}

    @staticmethod
    def load(path):
        data = Path(path).read_bytes(); jl = struct.unpack_from("<I", data, 12)[0]
        js = json.loads(data[20:20 + jl]); bo = 20 + jl; bl = struct.unpack_from("<I", data, bo)[0]
        return js, bytearray(data[bo + 8:bo + 8 + bl])

    @staticmethod
    def acc(js, binb, i):
        a = js["accessors"][i]; bv = js["bufferViews"][a["bufferView"]]
        off = bv.get("byteOffset", 0) + a.get("byteOffset", 0); n = a["count"] * glbio.NC[a["type"]]
        assert not bv.get("byteStride"), "interleaved buffers are not supported"
        return np.frombuffer(binb, glbio.CT[a["componentType"]], n, off).reshape(a["count"], -1).copy(), off, None

    @staticmethod
    def save(js, binb, out):
        jb = json.dumps(js, separators=(",", ":")).encode()
        while len(jb) % 4: jb += b" "
        o = (struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(jb) + 8 + len(binb)) + struct.pack("<II", len(jb), 0x4E4F534A)
             + jb + struct.pack("<II", len(binb), 0x004E4942) + bytes(binb))
        Path(out).write_bytes(o)


ap = argparse.ArgumentParser()
ap.add_argument("src"); ap.add_argument("out")
ap.add_argument("--box", default="-0.14,0.20,0.40,0.69")
ap.add_argument("--zmin", type=float, default=0.15)
ap.add_argument("--back-y", default="0.30,0.58")
ap.add_argument("--dilate", type=int, default=3)
ap.add_argument("--preview")
a = ap.parse_args()
x0, x1, y0, y1 = (float(v) for v in a.box.split(","))
by0, by1 = (float(v) for v in a.back_y.split(","))

js, b = glbio.load(a.src)
p = js["meshes"][0]["primitives"][0]
V = glbio.acc(js, b, p["attributes"]["POSITION"])[0].astype(np.float64)
UV = glbio.acc(js, b, p["attributes"]["TEXCOORD_0"])[0].astype(np.float64)
F = glbio.acc(js, b, p["indices"])[0].reshape(-1, 3).astype(np.int64)
ti = js["materials"][p.get("material", 0)]["pbrMetallicRoughness"]["baseColorTexture"]["index"]
ii = js["textures"][ti]["source"]; img = js["images"][ii]
bv = js["bufferViews"][img["bufferView"]]
raw = bytes(b[bv.get("byteOffset", 0):bv.get("byteOffset", 0) + bv["byteLength"]])
pil = Image.open(io.BytesIO(raw)); mode = pil.mode
T = np.asarray(pil.convert("RGBA")).astype(np.float64) / 255
H, Wd = T.shape[:2]

C = V[F].mean(1)
n = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]]); n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
uvc = UV[F].mean(1); pc = np.c_[(uvc[:, 0] * Wd).clip(0, Wd - 1), (uvc[:, 1] * H).clip(0, H - 1)].astype(int)
col = T[pc[:, 1], pc[:, 0], :3]
sat = col.max(1) - col.min(1); lum = col.mean(1)
gray = (sat < 0.08) & (lum > 0.12); gold = (col[:, 0] > 0.45) & (col[:, 0] - col[:, 2] > 0.12)
brown = (col[:, 0] - col[:, 2] > 0.04) & (lum < 0.25)
box = (C[:, 0] > x0) & (C[:, 0] < x1) & (C[:, 1] > y0) & (C[:, 1] < y1) & (C[:, 2] > a.zmin) & (n[:, 2] > 0.2)
sel = box & (gray | gold)
# grow one ring over non-brown box faces
vs = np.zeros(len(V), bool); vs[F[sel].ravel()] = True
sel |= box & ~brown & vs[F].any(1)
fsel = np.nonzero(sel)[0]

back = (n[:, 2] < -0.3) & (C[:, 2] < 0) & (C[:, 1] > by0 - 0.05) & (C[:, 1] < by1 + 0.05)
bidx = np.nonzero(back)[0]
tree = cKDTree(C[bidx][:, :2])

def bary2(P2, tri2):
    a_, b_, c_ = tri2
    v0, v1, v2 = b_ - a_, c_ - a_, P2 - a_
    d = v0[0] * v1[1] - v1[0] * v0[1]
    if abs(d) < 1e-14: return None
    l1 = (v2[..., 0] * v1[1] - v1[0] * v2[..., 1]) / d
    l2 = (v0[0] * v2[..., 1] - v2[..., 0] * v0[1]) / d
    return np.stack([1 - l1 - l2, l1, l2], -1)

def donor_uv(q):
    """q: (N,3) plate points -> (N,2) donor UV on the back skirt."""
    ys = by0 + (q[:, 1] - y0) / (y1 - y0) * (by1 - by0)
    Q = np.c_[q[:, 0], ys]
    _, nn = tree.query(Q, k=8)
    out = np.zeros((len(q), 2))
    for i in range(len(q)):
        best, bw = None, None
        for j in nn[i]:
            f = bidx[j]; tri = V[F[f]][:, :2]
            w = bary2(Q[i], tri)
            if w is None: continue
            m = w.min()
            if best is None or m > bw: best, bw, wb = f, m, w
        out[i] = wb.clip(0, 1) @ UV[F[best]] / max(wb.clip(0, 1).sum(), 1e-9)
    return out

def sample(uv):
    x = uv[:, 0] * Wd - 0.5; y = uv[:, 1] * H - 0.5
    xi = np.floor(x).astype(int); yi = np.floor(y).astype(int); fx = x - xi; fy = y - yi
    xi = xi.clip(0, Wd - 2); yi = yi.clip(0, H - 2)
    c = (T[yi, xi] * ((1 - fx) * (1 - fy))[:, None] + T[yi, xi + 1] * (fx * (1 - fy))[:, None]
         + T[yi + 1, xi] * ((1 - fx) * fy)[:, None] + T[yi + 1, xi + 1] * (fx * fy)[:, None])
    return c

# coverage of every face's UV triangle (for the overlap refusal and the gutter)
def raster(f):
    t = UV[F[f]] * [Wd, H]
    lo = np.floor(t.min(0)).astype(int) - 1; hi = np.ceil(t.max(0)).astype(int) + 1
    xs, ys = np.meshgrid(np.arange(lo[0], hi[0] + 1), np.arange(lo[1], hi[1] + 1))
    P2 = np.stack([xs + 0.5, ys + 0.5], -1).reshape(-1, 2)
    w = bary2(P2, t)
    if w is None: return np.zeros((0, 2), int), np.zeros((0, 3))
    m = (w >= -1e-6).all(1)
    return P2[m].astype(int), w[m]

owner = {}
write_px, write_q = [], []
for f in fsel:
    pxs, w = raster(f)
    for (xx, yy) in pxs: owner[(xx, yy)] = f
    write_px.append(pxs); write_q.append(w @ V[F[f]])
write_px = np.concatenate(write_px); write_q = np.concatenate(write_q)
mine = set(map(tuple, write_px))
# overlap check against non-selected faces whose UV bbox touches the written pixels
selset = set(fsel.tolist())
wmin = write_px.min(0); wmax = write_px.max(0)
uvt = UV[F] * [Wd, H]
cand = np.nonzero((uvt.max(1)[:, 0] >= wmin[0]) & (uvt.min(1)[:, 0] <= wmax[0]) & (uvt.max(1)[:, 1] >= wmin[1]) & (uvt.min(1)[:, 1] <= wmax[1]))[0]
other = set()
for f in cand:
    if f in selset: continue
    pxs, _ = raster(f)
    other.update(map(tuple, pxs))
clash = mine & other
# texels on a shared edge belong to both; refuse only on real overlap (more than edge texels)
if len(clash) > 0.02 * len(mine):
    raise SystemExit(f"plate texels overlap other faces' UVs: {len(clash)} of {len(mine)}")
keep = np.array([tuple(p_) not in other for p_ in write_px])
write_px, write_q = write_px[keep], write_q[keep]
# gutter: texels within `dilate` of a written texel, covered by no face, take the nearest written texel's point
if a.dilate:
    wt = cKDTree(write_px)
    lo = write_px.min(0) - a.dilate; hi = write_px.max(0) + a.dilate
    xs, ys = np.meshgrid(np.arange(lo[0], hi[0] + 1), np.arange(lo[1], hi[1] + 1))
    G = np.stack([xs, ys], -1).reshape(-1, 2)
    d, j = wt.query(G, distance_upper_bound=a.dilate + 0.01)
    ok = np.isfinite(d) & (d > 0)
    G, j = G[ok], j[ok]
    ok = np.array([tuple(g) not in other and tuple(g) not in mine for g in G], bool)
    write_px = np.concatenate([write_px, G[ok]]); write_q = np.concatenate([write_q, write_q[j[ok]]])
write_px = write_px[(write_px[:, 0] >= 0) & (write_px[:, 0] < Wd) & (write_px[:, 1] >= 0) & (write_px[:, 1] < H)]
write_q = write_q[:len(write_px)]
duv = donor_uv(write_q)
cols = sample(duv)
T2 = T.copy()
T2[write_px[:, 1], write_px[:, 0], :3] = cols[:, :3]
out_img = Image.fromarray((T2 * 255 + 0.5).clip(0, 255).astype(np.uint8), "RGBA").convert(mode if mode in ("RGB", "RGBA") else "RGBA")
buf = io.BytesIO(); out_img.save(buf, "PNG"); png = buf.getvalue()
while len(b) % 4: b += b"\0"
off = len(b); b += png
js["bufferViews"].append({"buffer": 0, "byteOffset": off, "byteLength": len(png)})
img["bufferView"] = len(js["bufferViews"]) - 1; img["mimeType"] = "image/png"
js["buffers"][0]["byteLength"] = len(b)
glbio.save(js, b, a.out)
sha = hashlib.sha256(open(a.out, "rb").read()).hexdigest()
src_sha = hashlib.sha256(open(a.src, "rb").read()).hexdigest()
print(f"plate faces {len(fsel)}; texels written {len(write_px)} (clash dropped {int((~keep).sum())}); out {a.out} {sha}")
rec = {"schema": "homm3_mesh_surgery.plate.v1", "input": a.src.replace("\\", "/"), "inputSha256": src_sha,
       "output": a.out.replace("\\", "/"), "outputSha256": sha,
       "tool": "tools/homm3_def_retarget/plate_surgery.py " + " ".join(sys.argv[3:]),
       "result": {"plateFaces": int(len(fsel)), "texelsWritten": int(len(write_px)), "box": [x0, x1, y0, y1], "backY": [by0, by1]},
       "reason": "authenticity h3_dwarf_battlerager 2026-10-09 (coordinator send-back 1): the DEF battlerager's resting maul head "
                 "was baked into the skirt front as a grey gold-studded plate; with the maul now a real prop (maul_m1) the plate "
                 "is re-painted with the skirt's own scale mail (texture only; geometry, UVs and skin unchanged)"}
json.dump(rec, open(a.out.rsplit(".glb", 1)[0] + ".surgery.json", "w"), indent=1)
if a.preview:
    m = np.zeros((H, Wd), bool); m[write_px[:, 1], write_px[:, 0]] = True
    ys_, xs_ = np.nonzero(m); c0 = np.array([xs_.min(), ys_.min()]) - 20; c1 = np.array([xs_.max(), ys_.max()]) + 20
    A = Image.fromarray((T[c0[1]:c1[1], c0[0]:c1[0], :3] * 255).astype(np.uint8)); B = Image.fromarray((T2[c0[1]:c1[1], c0[0]:c1[0], :3] * 255).astype(np.uint8))
    o = Image.new("RGB", (A.width * 2 + 10, A.height), (255, 255, 255)); o.paste(A, (0, 0)); o.paste(B, (A.width + 10, 0)); o.save(a.preview)
