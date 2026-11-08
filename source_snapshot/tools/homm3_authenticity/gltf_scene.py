"""GLB reader for the authenticity board: body mesh, skin, morph targets, base-colour image and clip sampling.

Reuses the repo's GLB readers instead of a new parser:
  - tools/homm3_def_retarget/articulation.py ``load`` (accessor decoding) and ``qmat`` / ``trs``;
  - tools/homm3_unit_look/glbpatch.py ``Glb`` (body mesh = largest mesh not on a ``*_Rubble`` node, its one
    base-colour image).
Animation sampling (LINEAR / STEP / CUBICSPLINE, glTF 2.0 rules) and the node hierarchy run on the CPU in float64:
a few dozen joints x a few hundred times is inherently a sequential parent-before-child walk and costs milliseconds;
the per-vertex work (morphs, skinning) and rasterisation run on the board's torch device (raster.py).
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/homm3_def_retarget"))
sys.path.insert(0, str(ROOT / "tools/homm3_unit_look"))
from articulation import CT, NC, load as glb_load  # noqa: E402
from glbpatch import Glb  # noqa: E402


def _quat_to_mat(q: np.ndarray) -> np.ndarray:
    """(..., 4) xyzw -> (..., 3, 3)."""
    q = q / np.maximum(np.linalg.norm(q, axis=-1, keepdims=True), 1e-12)
    x, y, z, w = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    m = np.empty(q.shape[:-1] + (3, 3))
    m[..., 0, 0] = 1 - 2 * (y * y + z * z); m[..., 0, 1] = 2 * (x * y - z * w); m[..., 0, 2] = 2 * (x * z + y * w)
    m[..., 1, 0] = 2 * (x * y + z * w); m[..., 1, 1] = 1 - 2 * (x * x + z * z); m[..., 1, 2] = 2 * (y * z - x * w)
    m[..., 2, 0] = 2 * (x * z - y * w); m[..., 2, 1] = 2 * (y * z + x * w); m[..., 2, 2] = 1 - 2 * (x * x + y * y)
    return m


def _slerp(a: np.ndarray, b: np.ndarray, u: np.ndarray) -> np.ndarray:
    d = np.sum(a * b, -1, keepdims=True)
    b = np.where(d < 0, -b, b)
    d = np.abs(d)
    th = np.arccos(np.clip(d, -1, 1))
    s = np.sin(th)
    small = s < 1e-6
    wa = np.where(small, 1 - u, np.sin((1 - u) * th) / np.where(small, 1, s))
    wb = np.where(small, u, np.sin(u * th) / np.where(small, 1, s))
    r = wa * a + wb * b
    return r / np.maximum(np.linalg.norm(r, axis=-1, keepdims=True), 1e-12)


def sample_channel(ti: np.ndarray, vo: np.ndarray, interp: str, t: np.ndarray, rot: bool) -> np.ndarray:
    """glTF sampler at times t. ti (K,), vo (K, C) [CUBICSPLINE: (3K, C) in/value/out triplets] -> (len(t), C)."""
    K = len(ti)
    if interp == "CUBICSPLINE":
        vo = vo.reshape(K, 3, -1)
        val, a_in, b_out = vo[:, 1], vo[:, 0], vo[:, 2]
    else:
        val = vo.reshape(K, -1)
    tc = np.clip(t, ti[0], ti[-1])
    k = np.clip(np.searchsorted(ti, tc, side="right") - 1, 0, K - 1)
    k1 = np.minimum(k + 1, K - 1)
    dt = ti[k1] - ti[k]
    u = np.where(dt > 0, (tc - ti[k]) / np.where(dt > 0, dt, 1), 0.0)[:, None]
    if interp == "STEP":
        out = val[k]
    elif interp == "CUBICSPLINE":
        u2, u3 = u * u, u * u * u
        d = dt[:, None]
        out = ((2 * u3 - 3 * u2 + 1) * val[k] + (u3 - 2 * u2 + u) * d * b_out[k]
               + (-2 * u3 + 3 * u2) * val[k1] + (u3 - u2) * d * a_in[k1])
        if rot:
            out = out / np.maximum(np.linalg.norm(out, axis=-1, keepdims=True), 1e-12)
    elif rot:
        out = _slerp(val[k], val[k1], u)
    else:
        out = val[k] * (1 - u) + val[k1] * u
    return out


def _sparse_aware(path: Path, g: dict, dense):
    """articulation.load's accessor reader plus glTF sparse accessors (a base of zeros when there is no bufferView,
    then indices -> values), which the delivery stages write for sparse morph-weight / key tracks."""
    import struct
    binb = None

    def raw(view: int, ctype: int, count: int, ncomp: int, off: int = 0) -> np.ndarray:
        nonlocal binb
        if binb is None:
            b = path.read_bytes()
            jl = struct.unpack_from("<I", b, 12)[0]
            bl = struct.unpack_from("<I", b, 20 + jl)[0]
            binb = b[28 + jl:28 + jl + bl]
        bv = g["bufferViews"][view]
        dt = np.dtype(CT[ctype])
        return np.frombuffer(binb, dt, count * ncomp, bv.get("byteOffset", 0) + off).reshape(count, ncomp)

    def acc(i: int) -> np.ndarray:
        a = g["accessors"][i]
        sp = a.get("sparse")
        if not sp:
            return dense(i)
        n = NC[a["type"]]
        norm = a.get("normalized") and np.issubdtype(np.dtype(CT[a["componentType"]]), np.integer)
        if "bufferView" in a:
            base = dense(i).copy()                       # already normalised by articulation.load
        else:
            base = np.zeros((a["count"], n), np.float32 if norm else CT[a["componentType"]])
        if sp["count"]:
            ix = raw(sp["indices"]["bufferView"], sp["indices"]["componentType"], sp["count"], 1,
                     sp["indices"].get("byteOffset", 0))[:, 0].astype(np.int64)
            vals = raw(sp["values"]["bufferView"], a["componentType"], sp["count"], n, sp["values"].get("byteOffset", 0))
            if norm:
                vals = vals.astype(np.float32) / np.iinfo(CT[a["componentType"]]).max
            base[ix] = vals
        return base
    return acc


class Scene:
    """One GLB: the body mesh (one skinned mesh, every primitive merged), its skin, morphs and animations."""

    def __init__(self, path: Path, body_name: str | None = None, skip_meshes=()):
        self.path = Path(path)
        g, dense = glb_load(str(self.path))
        acc = _sparse_aware(self.path, g, dense)
        self.g, self._acc = g, acc
        glb = Glb(self.path.read_bytes())   # released at the end of __init__ (only the image bytes are kept)
        nodes = g["nodes"]
        self.nodes = nodes
        self.parent = {c: i for i, n in enumerate(nodes) for c in n.get("children", [])}
        order, stack = [], [i for i in range(len(nodes)) if i not in self.parent][::-1]
        while stack:
            i = stack.pop(); order.append(i); stack += nodes[i].get("children", [])[::-1]
        self.order = order
        body_mesh = glb.body_mesh_index()
        skinned = [i for i, n in enumerate(nodes) if n.get("mesh") == body_mesh and "skin" in n]
        if body_name is not None:
            named = [i for i in skinned if nodes[i].get("name") == body_name]
            skinned = named or skinned
        if len(skinned) != 1:
            raise SystemExit(f"{self.path.name}: expected one skinned node for body mesh {body_mesh}, found {skinned}")
        self.body_node = skinned[0]
        self.body_name = nodes[self.body_node].get("name")
        mesh = g["meshes"][body_mesh]
        skin = g["skins"][nodes[self.body_node]["skin"]]
        # a second mesh on the body's own skin and material (a death shatter's *_Rubble chunks, hidden by bone scale
        # until the break) renders with the body; any other mesh stays unrendered and is listed as such
        body_mats = {p.get("material") for p in mesh["primitives"]}
        self.extra_nodes = [i for i, n in enumerate(nodes) if "mesh" in n and i != self.body_node and n.get("mesh") != body_mesh
                            and n.get("skin") == nodes[self.body_node]["skin"]
                            and {p.get("material") for p in g["meshes"][n["mesh"]]["primitives"]} <= body_mats
                            and n.get("name") not in set(skip_meshes)]   # the slice row's deferMeshes: not in game
        self.other_meshes = [nodes[i].get("name") for i, n in enumerate(nodes)
                             if "mesh" in n and i != self.body_node and i not in self.extra_nodes]
        self.joints = list(skin["joints"])
        self.ibm = (acc(skin["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1).astype(np.float64)
                    if "inverseBindMatrices" in skin else np.tile(np.eye(4), (len(self.joints), 1, 1)))
        P, N, UV, J, W, F, T = [], [], [], [], [], [], []
        mats = set()
        off = 0
        ntargets = None
        prims = [(p, True) for p in mesh["primitives"]] + [(p, False) for i in self.extra_nodes for p in g["meshes"][nodes[i]["mesh"]]["primitives"]]
        for p, is_body in prims:
            if p.get("mode", 4) != 4:
                raise SystemExit(f"{self.path.name}: primitive mode {p.get('mode')} is not triangles")
            a = p["attributes"]
            pos = acc(a["POSITION"]).astype(np.float64)
            n = len(pos)
            P.append(pos)
            N.append(acc(a["NORMAL"]).astype(np.float64) if "NORMAL" in a else np.zeros((n, 3)))
            UV.append(acc(a["TEXCOORD_0"]).astype(np.float64) if "TEXCOORD_0" in a else np.zeros((n, 2)))
            J.append(acc(a["JOINTS_0"]).astype(np.int64))
            W.append(acc(a["WEIGHTS_0"]).astype(np.float64))
            idx = acc(p["indices"]).reshape(-1).astype(np.int64) if "indices" in p else np.arange(n)
            F.append(idx.reshape(-1, 3) + off)
            tg = p.get("targets", [])
            if not is_body:                      # rubble carries no corrective morphs: zero offsets for the body's targets
                T.append(np.zeros((ntargets or 0, n, 3), np.float32)); mats.add(p.get("material")); off += n
                continue
            if ntargets is None:
                ntargets = len(tg)
            if len(tg) != ntargets:
                raise SystemExit(f"{self.path.name}: primitives disagree on morph target count")
            T.append(np.stack([acc(t["POSITION"]).astype(np.float32) for t in tg]) if tg else np.zeros((0, n, 3), np.float32))
            mats.add(p.get("material"))
            off += n
        self.P = np.concatenate(P)
        self.N = np.concatenate(N)
        self.UV = np.concatenate(UV)
        self.J = np.concatenate(J)
        W = np.concatenate(W)
        self.W = W / np.maximum(W.sum(1, keepdims=True), 1e-12)
        self.F = np.concatenate(F)
        self.morphs = np.concatenate(T, axis=1) if ntargets else np.zeros((0, len(self.P), 3), np.float32)
        self.default_weights = np.array(mesh.get("weights", [0.0] * (ntargets or 0)), np.float64)
        if len(mats) != 1 or None in mats:
            raise SystemExit(f"{self.path.name}: body mesh uses materials {sorted(map(str, mats))}; the board renders one")
        mat = g["materials"][mats.pop()]
        pbr = mat.get("pbrMetallicRoughness", {})
        self.base_color_factor = np.array(pbr.get("baseColorFactor", [1, 1, 1, 1]), np.float64)
        self.alpha_mode = mat.get("alphaMode", "OPAQUE")
        self.alpha_cutoff = float(mat.get("alphaCutoff", 0.5))
        self.image_index = glb.body_base_color_image()
        self.image_bytes = glb.image_bytes(self.image_index)
        self.anims = {a.get("name", f"anim{i}"): a for i, a in enumerate(g.get("animations", []))}
        self.rest = [(np.array(n.get("translation", [0, 0, 0]), np.float64), np.array(n.get("rotation", [0, 0, 0, 1]), np.float64),
                      np.array(n.get("scale", [1, 1, 1]), np.float64)) for n in nodes]
        for i, n in enumerate(nodes):
            if "matrix" in n and n["matrix"] != [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]:
                raise SystemExit(f"{self.path.name}: node {n.get('name')} uses a matrix; the board samples TRS only")
        self.extras = g.get("asset", {}).get("extras", {})
        # decode every animation channel now and drop the GLB buffers (tens of MB the board does not need again)
        self.channels = {}
        for name, a in self.anims.items():
            chans = []
            for ch in a["channels"]:
                tgt = ch["target"]
                if "node" not in tgt:
                    continue
                s = a["samplers"][ch["sampler"]]
                chans.append((tgt["path"], tgt["node"], acc(s["input"]).reshape(-1).astype(np.float64),
                              acc(s["output"]).astype(np.float64), s.get("interpolation", "LINEAR")))
            self.channels[name] = chans
        self.g = self._acc = None

    def texture_rgba(self, max_size: int = 1024) -> np.ndarray:
        from PIL import Image
        im = Image.open(io.BytesIO(self.image_bytes)).convert("RGBA")
        if max(im.size) > max_size:
            s = max_size / max(im.size)
            im = im.resize((max(1, round(im.size[0] * s)), max(1, round(im.size[1] * s))), Image.LANCZOS)
        return np.asarray(im, np.float32) / 255.0

    def clip_names(self) -> list[str]:
        return list(self.anims)

    def clip_range(self, name: str) -> dict:
        """Key-time facts of one clip: start (the most common first-key time over its channels, so a stage that
        prepends a 0 s key to a few channels does not move the DEF grid), end (last key of any channel)."""
        firsts, last = [], 0.0
        for _, _, ti, _, _ in self.channels[name]:
            firsts.append(round(float(ti[0]), 5))
            last = max(last, float(ti[-1]))
        vals, cnt = np.unique(firsts, return_counts=True)
        return {"start": float(vals[np.argmax(cnt)]), "end": last, "duration": last - float(vals[np.argmax(cnt)])}

    def pose(self, name: str, times: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(joint matrices (T, J, 4, 4) float64 = global(joint) @ IBM, morph weights (T, M) float64)."""
        times = np.asarray(times, np.float64)
        T = len(times)
        nn = len(self.nodes)
        tr = np.broadcast_to(np.array([r[0] for r in self.rest]), (T, nn, 3)).copy()
        ro = np.broadcast_to(np.array([r[1] for r in self.rest]), (T, nn, 4)).copy()
        sc = np.broadcast_to(np.array([r[2] for r in self.rest]), (T, nn, 3)).copy()
        M = self.morphs.shape[0]
        mw = np.broadcast_to(self.default_weights, (T, M)).copy() if M else np.zeros((T, 0))
        for path, node, ti, vo, interp in self.channels[name]:
            if path == "weights":
                if node != self.body_node:
                    continue
                mw = sample_channel(ti, vo.reshape(-1, M), interp, times, False)   # (K or 3K, M)
                continue
            v = sample_channel(ti, vo, interp, times, path == "rotation")
            if path == "translation":
                tr[:, node] = v
            elif path == "rotation":
                ro[:, node] = v
            elif path == "scale":
                sc[:, node] = v
        R = _quat_to_mat(ro)                       # (T, nn, 3, 3)
        L = np.zeros((T, nn, 4, 4))
        L[..., :3, :3] = R * sc[..., None, :]
        L[..., :3, 3] = tr
        L[..., 3, 3] = 1
        G = np.zeros_like(L)
        for i in self.order:
            p = self.parent.get(i)
            G[:, i] = L[:, i] if p is None else G[:, p] @ L[:, i]
        Jm = G[:, self.joints] @ self.ibm[None]
        return Jm, mw
