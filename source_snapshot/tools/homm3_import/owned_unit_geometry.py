"""Read an owned-skinned HoMM3 unit bundle and pose it the way the plugin does (static, read-only).

Library for measure_owned_unit_presentation.py / validate_homm3_owned_unit_presentation_contract.py.

What it reproduces (Homm3ImportVisuals.cs):
  * the prefab root is the GameObject carrying the Animator and the ``__homm3_skinned_battle_lane__`` child;
  * ``EnsureOwnedSkinnedDeliveryOrientation`` zeroes the ``Orientation`` / ``MocapDeliveryRoot`` wrap before
    any fit (``zero_orientation=True``), and every lane later sets it to a pure yaw (does not change heights);
  * ``SampleOwnedSkinnedIdlePose`` = the idle override clip (``22.Idle``) at t=0;
  * ``TryGetRenderableWorldBounds`` = merged ``TransformLocalBoundsToWorld(skin.transform, skin.localBounds)``.
    Every owned bundle ships ``m_UpdateWhenOffscreen: 1`` with an empty ``m_AABB``, so ``localBounds`` is Unity's
    bone-based bound: each bone's ``Mesh.m_BonesAABB`` box (bind space) through the bone's current matrix, merged
    and expressed in the root bone's space (``unity_bone_bounds``). The model is checked against the live
    ``skinned fit source=hex ... meshY=`` log lines by measure_owned_unit_presentation.py (--calibrate).
  * the exact silhouette: every vertex skinned (blend shapes applied) at a clip time (``skinned_points``).

Proof tier: static read of built / installed bundles with UnityPy; poses are decoded clip samples, not captures.
"""
from __future__ import annotations

import os
import struct
import sys
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
MARKER = "__homm3_skinned_battle_lane__"
WRAP_NODES = ("Orientation", "MocapDeliveryRoot")
GOLDEN_ERA = Path(r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era")
INSTALLED_BUNDLES = GOLDEN_ERA / "BepInEx/plugins/OfflineUnlockMod/homm3_bundles"


def quat_mat(q) -> np.ndarray:
    x, y, z, w = q
    n = x * x + y * y + z * z + w * w
    if n < 1e-12:
        return np.eye(3)
    s = 2.0 / n
    return np.array([[1 - s * (y * y + z * z), s * (x * y - z * w), s * (x * z + y * w)],
                     [s * (x * y + z * w), 1 - s * (x * x + z * z), s * (y * z - x * w)],
                     [s * (x * z - y * w), s * (y * z + x * w), 1 - s * (x * x + y * y)]])


def trs(t, q, s) -> np.ndarray:
    m = np.eye(4)
    m[:3, :3] = quat_mat(q) * np.asarray(s, dtype=np.float64)[None, :]
    m[:3, 3] = t
    return m


def decode_streamed(words) -> dict[int, tuple[np.ndarray, np.ndarray]]:
    """Unity StreamedClip: frames of (time, nKeys, nKeys x (curveIndex, coeff[4])) -> {curve: (times, coeffs)}."""
    buf = struct.pack(f"<{len(words)}I", *words)
    pos, curves = 0, {}
    while pos < len(buf):
        t, n = struct.unpack_from("<fI", buf, pos)
        pos += 8
        for _ in range(n):
            idx = struct.unpack_from("<I", buf, pos)[0]
            c = struct.unpack_from("<4f", buf, pos + 4)
            pos += 20
            if np.isfinite(t):
                curves.setdefault(idx, []).append((t, c))
    return {k: (np.array([a for a, _ in v]), np.array([b for _, b in v])) for k, v in curves.items()}


def eval_streamed(kc, times: np.ndarray) -> np.ndarray:
    kt, co = kc
    j = np.clip(np.searchsorted(kt, times, side="right") - 1, 0, len(kt) - 1)
    dt = times - kt[j]
    a, b, c, d = co[j, 0], co[j, 1], co[j, 2], co[j, 3]
    return ((a * dt + b) * dt + c) * dt + d


@dataclass
class Clip:
    name: str
    start: float
    stop: float
    loop: bool
    transform: dict[str, dict[int, np.ndarray]]  # pathHash -> attr -> (T, k)
    blend: dict[int, np.ndarray]  # binding attribute = the mesh channel nameHash (crc32 of the bare shape name) -> (T,)
    times: np.ndarray


def sample_clip(tt: dict, times: np.ndarray | None = None, hz: float = 30.0) -> Clip:
    mc = tt["m_MuscleClip"]
    start, stop = float(mc["m_StartTime"]), float(mc["m_StopTime"])
    if times is None:
        times = np.linspace(start, stop, max(2, int(round((stop - start) * hz)) + 1))
    data = mc["m_Clip"]["data"]
    sc, dc, cc = data["m_StreamedClip"], data["m_DenseClip"], data["m_ConstantClip"]["data"]
    n_s, n_d = int(sc["curveCount"]), int(dc["m_CurveCount"])
    streamed = decode_streamed(sc["data"]) if sc["data"] else {}
    dense = np.asarray(dc["m_SampleArray"], dtype=np.float64)
    dtimes = None
    if n_d:
        dense = dense.reshape(int(dc["m_FrameCount"]), n_d)
        dtimes = float(dc["m_BeginTime"]) + np.arange(dense.shape[0]) / float(dc["m_SampleRate"])

    def curve(i: int) -> np.ndarray:
        if i < n_s:
            k = streamed.get(i)
            return eval_streamed(k, times) if k is not None else np.zeros(len(times))
        i -= n_s
        if i < n_d:
            return np.interp(times, dtimes, dense[:, i])
        return np.full(len(times), float(cc[i - n_d]))

    tr: dict[str, dict[int, np.ndarray]] = {}
    bl: dict[int, np.ndarray] = {}
    ci = 0
    for b in tt["m_ClipBindingConstant"]["genericBindings"]:
        tid, attr = int(b["typeID"]), int(b["attribute"])
        if tid == 4:
            size = 4 if attr == 2 else 3
            tr.setdefault(str(b["path"]), {})[attr] = np.stack([curve(ci + k) for k in range(size)], 1)
        else:
            size = 1
            if tid == 137:
                bl[attr & 0xFFFFFFFF] = curve(ci)
        ci += size
    loop = bool(mc.get("m_LoopTime", 0))
    return Clip(tt.get("m_Name", "?"), start, stop, loop, tr, bl, times)


@dataclass
class Skin:
    name: str
    node: int
    root_bone: int | None
    bones: list[int]
    verts: np.ndarray  # (V,3) bind space
    bi: np.ndarray  # (V,4)
    bw: np.ndarray  # (V,4)
    bind: np.ndarray  # (B,4,4)
    bone_aabb: np.ndarray  # (B,2,3) min,max ; min>max marks empty
    shapes: list[tuple[int, float, np.ndarray, np.ndarray]]  # (channel nameHash, fullWeight, idx, delta)
    default_weights: np.ndarray
    material_shaders: list[str]
    material_names: list[str]


@dataclass
class Unit:
    bundle: str
    root: int
    names: dict[int, str]
    parent: dict[int, int | None]
    children: dict[int, list[int]]
    local: dict[int, list]  # t, q, s
    skins: list[Skin]
    clips: dict[str, Clip]  # native slot name (e.g. 22.Idle) -> clip (all times)
    clip_by_override: dict[str, str]
    wrap: int | None
    anim: int  # the Animator's node: clip binding paths are relative to it
    extra: dict[str, Any] = field(default_factory=dict)

    # -- hierarchy ---------------------------------------------------------------------------
    def path(self, pid: int) -> str:
        parts = []
        while pid is not None and pid != self.anim:
            parts.append(self.names[pid])
            pid = self.parent[pid]
        return "/".join(reversed(parts))

    def find(self, name: str) -> int | None:
        return next((k for k, v in self.names.items() if v == name), None)

    def pose_locals(self, clip: Clip | None, ti: int, zero_wrap: bool = True) -> dict[int, list]:
        loc = {k: [list(v[0]), list(v[1]), list(v[2])] for k, v in self.local.items()}
        if clip is not None:
            byhash = self.extra.setdefault("byhash", {str(zlib.crc32(self.path(p).encode())): p
                                                       for p in self.names if p != self.anim})
            for h, attrs in clip.transform.items():
                p = byhash.get(h)
                if p is None:
                    continue
                if 1 in attrs:
                    loc[p][0] = attrs[1][ti]
                if 2 in attrs:
                    loc[p][1] = attrs[2][ti]
                if 3 in attrs:
                    loc[p][2] = attrs[3][ti]
        if zero_wrap and self.wrap is not None:
            loc[self.wrap][1] = [0.0, 0.0, 0.0, 1.0]
        return loc

    def world(self, loc: dict[int, list]) -> dict[int, np.ndarray]:
        out: dict[int, np.ndarray] = {}

        def wm(p: int) -> np.ndarray:
            if p not in out:
                m = trs(*loc[p])
                par = self.parent[p]
                out[p] = m if par is None or p == self.root else wm(par) @ m
            return out[p]

        for p in self.names:
            wm(p)
        # measure in the prefab root's space
        inv = np.linalg.inv(out[self.root])
        return {k: inv @ v for k, v in out.items()}

    def blend_weights(self, skin: Skin, clip: Clip | None, ti: int) -> np.ndarray:
        w = skin.default_weights.copy()
        if clip is not None and clip.blend:
            for i, (h, _, _, _) in enumerate(skin.shapes):
                if h in clip.blend:
                    w[i] = clip.blend[h][ti]
        return w

    def skinned_points(self, clip: Clip | None = None, ti: int = 0, zero_wrap: bool = True) -> np.ndarray:
        W = self.world(self.pose_locals(clip, ti, zero_wrap))
        pts = []
        for s in self.skins:
            v = s.verts
            if s.shapes:
                w = self.blend_weights(s, clip, ti)
                if np.any(np.abs(w) > 1e-6):
                    v = v.copy()
                    for (h, full, idx, d), wt in zip(s.shapes, w):
                        if abs(wt) > 1e-6:
                            v[idx] += d * (wt / (full if full else 1.0))
            vh = np.c_[v, np.ones(len(v))]
            if s.bones:
                mats = np.stack([W[b] @ s.bind[i] if b in W else np.eye(4) for i, b in enumerate(s.bones)])
                M = np.einsum("vk,vkij->vij", s.bw, mats[s.bi])
                pts.append(np.einsum("vij,vj->vi", M, vh)[:, :3])
            else:
                pts.append((W[s.node] @ vh.T).T[:, :3])
        return np.concatenate(pts) if pts else np.zeros((0, 3))

    def unity_bone_bounds(self, clip: Clip | None = None, ti: int = 0, zero_wrap: bool = True):
        """(plugin-read bounds as used by TryGetRenderableWorldBounds, true-space bone bounds), both in root space.

        Unity's updateWhenOffscreen bound: each bone's m_BonesAABB box through its current matrix, merged
        (world), stored relative to the root bone (localBounds). The plugin then pushes localBounds through
        skin.transform, which is only right when the root bone and the renderer share a frame.
        """
        W = self.world(self.pose_locals(clip, ti, zero_wrap))
        plugin, true = [], []
        for s in self.skins:
            corners = []
            for i, b in enumerate(s.bones):
                lo, hi = s.bone_aabb[i]
                if np.any(lo > hi) or b not in W:
                    continue
                c = np.array([[x, y, z, 1.0] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
                corners.append((W[b] @ c.T).T[:, :3])
            if not corners:
                continue
            wc = np.concatenate(corners)
            true.append((wc.min(0), wc.max(0)))
            rb = s.root_bone if s.root_bone in W else s.node
            loc = (np.linalg.inv(W[rb]) @ np.c_[wc, np.ones(len(wc))].T).T[:, :3]
            lo, hi = loc.min(0), loc.max(0)
            c = np.array([[x, y, z, 1.0] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
            pc = (W[s.node] @ c.T).T[:, :3]
            plugin.append((pc.min(0), pc.max(0)))

        def merge(bs):
            if not bs:
                return None
            return np.min([b[0] for b in bs], 0), np.max([b[1] for b in bs], 0)

        return merge(plugin), merge(true)




def _vec(d: dict, keys=("x", "y", "z", "w")) -> list[float]:
    return [float(d[k]) for k in keys if k in d]


class _Tree:
    """Transform hierarchy reached from one root, over any UnityPy object table (bundle or resources.assets)."""

    def __init__(self, objs: dict, root_tr: int):
        self.objs = objs
        self.names, self.parent, self.children, self.local, self.go, self.comps = {}, {}, {}, {}, {}, {}
        self.active: dict[int, bool] = {}
        stack = [(root_tr, None, True)]
        while stack:
            pid, par, act = stack.pop()
            t = objs[pid].read_typetree()
            go = objs[t["m_GameObject"]["m_PathID"]].read_typetree()
            self.names[pid] = go["m_Name"]
            self.parent[pid] = par
            self.children[pid] = [c["m_PathID"] for c in t["m_Children"] if c["m_PathID"] in objs]
            self.local[pid] = [_vec(t["m_LocalPosition"]), _vec(t["m_LocalRotation"]), _vec(t["m_LocalScale"])]
            self.go[pid] = go
            self.comps[pid] = [objs[c["component"]["m_PathID"]] for c in go["m_Component"]
                               if c["component"]["m_FileID"] == 0 and c["component"]["m_PathID"] in objs]
            a = act and bool(go.get("m_IsActive", 1))
            self.active[pid] = a
            stack += [(c, pid, a) for c in self.children[pid]]
        self.root = root_tr

    def subtree(self, pid: int) -> set[int]:
        out, stack = set(), [pid]
        while stack:
            p = stack.pop()
            out.add(p)
            stack += self.children.get(p, [])
        return out


def _read_skin(objs: dict, tree: _Tree, p: int, comp) -> Skin | None:
    from UnityPy.helpers.MeshHelper import MeshHandler

    rt = comp.read_typetree()
    if not rt.get("m_Enabled", 1):
        return None
    if comp.type.name == "SkinnedMeshRenderer":
        mref = rt["m_Mesh"]
    else:
        mf = next((x for x in tree.comps[p] if x.type.name == "MeshFilter"), None)
        mref = mf.read_typetree()["m_Mesh"] if mf else None
    mo = objs.get(mref["m_PathID"]) if mref and mref["m_FileID"] == 0 else None
    if mo is None:
        return None
    mesh = mo.read()
    mt = mo.read_typetree()
    h = MeshHandler(mesh)
    h.process()
    v = np.asarray(h.m_Vertices, dtype=np.float64)[:, :3]
    n = len(v)
    bones = [b["m_PathID"] for b in rt.get("m_Bones", [])] if comp.type.name == "SkinnedMeshRenderer" else []
    bi = np.zeros((n, 4), dtype=np.int64)
    bw = np.zeros((n, 4))
    if bones and h.m_BoneIndices:
        idx = np.asarray(h.m_BoneIndices, dtype=np.int64)
        bi[:, :min(4, idx.shape[1])] = idx[:, :4]
        if h.m_BoneWeights:
            w = np.asarray(h.m_BoneWeights, dtype=np.float64)
            bw[:, :min(4, w.shape[1])] = w[:, :4]
        else:
            bw[:, 0] = 1.0
        bw /= np.maximum(bw.sum(1, keepdims=True), 1e-9)
    elif bones:
        bones = []
    bind = np.stack([np.array([[getattr(b, f"e{r}{cc}") for cc in range(4)] for r in range(4)])
                     for b in mesh.m_BindPose]) if bones else np.zeros((0, 4, 4))
    if bones and mt.get("m_BonesAABB"):
        baabb = np.array([[_vec(a["m_Min"]), _vec(a["m_Max"])] for a in mt["m_BonesAABB"]])
    else:
        baabb = np.zeros((len(bones), 2, 3))
        baabb[:, 0], baabb[:, 1] = 1.0, -1.0
    shapes = []
    sh = mt["m_Shapes"]
    if sh["channels"]:
        sv = sh["vertices"]
        for ch in sh["channels"]:
            fi, fc = int(ch["frameIndex"]), int(ch["frameCount"])
            if fc < 1:
                continue
            last = fi + fc - 1  # full-weight frame
            shp = sh["shapes"][last]
            a, k = int(shp["firstVertex"]), int(shp["vertexCount"])
            ids = np.array([int(x["index"]) for x in sv[a:a + k]], dtype=np.int64)
            d = np.array([_vec(x["vertex"], ("x", "y", "z")) for x in sv[a:a + k]]).reshape(-1, 3)
            full = float(sh["fullWeights"][last]) if sh["fullWeights"] else 100.0
            shapes.append((int(ch["nameHash"]) & 0xFFFFFFFF, full, ids, d))
    dw = np.zeros(len(shapes))
    for i, x in enumerate(rt.get("m_BlendShapeWeights", [])[:len(shapes)]):
        dw[i] = float(x)
    shaders, mnames = [], []
    for m in rt["m_Materials"]:
        mo2 = objs.get(m["m_PathID"]) if m["m_FileID"] == 0 else None
        if mo2 is None:
            shaders.append("?external")
            mnames.append("?")
            continue
        mtt = mo2.read_typetree()
        mnames.append(mtt["m_Name"])
        sref = mtt["m_Shader"]
        so = objs.get(sref["m_PathID"]) if sref["m_FileID"] == 0 else None
        shaders.append(so.peek_name() if so is not None else "?external")
    rb = (rt.get("m_RootBone") or {}).get("m_PathID") or None
    return Skin(tree.names[p], p, rb, bones, v, bi, bw, bind, baabb, shapes, dw, shaders, mnames)


def _clips(objs: dict, ctrl_ref: dict, clip_hz: float, want_clips: bool) -> tuple[dict, dict]:
    clips: dict[str, Clip] = {}
    by_override: dict[str, str] = {}
    ctrl = objs.get(ctrl_ref["m_PathID"]) if ctrl_ref["m_FileID"] == 0 else None
    if ctrl is None or ctrl.type.name != "AnimatorOverrideController":
        return clips, by_override
    cache: dict[int, Clip] = {}
    for cl in ctrl.read_typetree()["m_Clips"]:
        orig = objs.get(cl["m_OriginalClip"]["m_PathID"])
        ov = objs.get(cl["m_OverrideClip"]["m_PathID"])
        if orig is None or ov is None:
            continue
        slot = orig.peek_name()
        if not want_clips and slot != "22.Idle":
            continue
        if ov.path_id not in cache:
            cache[ov.path_id] = sample_clip(ov.read_typetree(), hz=clip_hz)
        clips[slot] = cache[ov.path_id]
        by_override[slot] = ov.peek_name()
    return clips, by_override


def _unit(label: str, objs: dict, tree: _Tree, root: int, anim: int, ctrl_ref: dict, wrap: int | None,
          clip_hz: float, want_clips: bool) -> Unit:
    skins = []
    for p in tree.subtree(anim):
        if not tree.active[p]:
            continue
        for c in tree.comps[p]:
            if c.type.name in ("SkinnedMeshRenderer", "MeshRenderer"):
                s = _read_skin(objs, tree, p, c)
                if s is not None:
                    skins.append(s)
    clips, by_override = _clips(objs, ctrl_ref, clip_hz, want_clips)
    return Unit(label, root, tree.names, tree.parent, tree.children, tree.local, skins, clips, by_override, wrap, anim)


def load_unit(bundle_path: Path, clip_hz: float = 30.0, want_clips: bool = True) -> Unit:
    """The owned-skinned prefab in a built / installed bundle (Animator + lane marker on the root)."""
    import UnityPy

    env = UnityPy.load(str(bundle_path))
    objs = {o.path_id: o for o in env.objects}
    cands = []
    for o in env.objects:
        if o.type.name != "Transform":
            continue
        t = o.read_typetree()
        if t["m_Father"]["m_PathID"]:
            continue
        kids = [objs[c["m_PathID"]].read_typetree() for c in t["m_Children"] if c["m_PathID"] in objs]
        if not any(objs[k["m_GameObject"]["m_PathID"]].peek_name() == MARKER for k in kids):
            continue
        go = objs[t["m_GameObject"]["m_PathID"]].read_typetree()
        if any(c["component"]["m_PathID"] in objs and objs[c["component"]["m_PathID"]].type.name == "Animator"
               for c in go["m_Component"]):
            cands.append(o.path_id)
    if len(cands) != 1:
        raise ValueError(f"{bundle_path.name}: expected one owned-skinned prefab root (Animator + {MARKER}), found {len(cands)}")
    root = cands[0]
    tree = _Tree(objs, root)
    wrap = next((c for c in tree.children[root] if tree.names.get(c) in WRAP_NODES), None)
    anim = next(c for c in tree.comps[root] if c.type.name == "Animator").read_typetree()
    u = _unit(bundle_path.name, objs, tree, root, root, anim["m_Controller"], wrap, clip_hz, want_clips)
    ab = next((o for o in env.objects if o.type.name == "AssetBundle"), None)
    u.extra["container"] = [k for k, _ in ab.read_typetree()["m_Container"]] if ab is not None else []
    return u


class StockPrefabs:
    """Vanilla battle / map prefabs from the installed resources.assets (read-only)."""

    def __init__(self, game_data: Path = GOLDEN_ERA / "HeroesOldenEra_Data"):
        import UnityPy

        env = UnityPy.load(str(game_data / "globalgamemanagers"), str(game_data / "resources.assets"))
        rm = next(o for o in env.objects if o.type.name == "ResourceManager").read_typetree()
        self.container = {k.lower(): p["m_PathID"] for k, p in rm["m_Container"]}
        ra = next(f for n, f in env.files.items() if n.endswith("resources.assets"))
        self.objs = ra.objects

    def load(self, key: str, view_scale: float | None, clip_hz: float = 30.0, want_clips: bool = True) -> Unit:
        """key: container path under units/ (lower case). view_scale replaces the first child's scale magnitude
        (UiModelsSpawner rule, tools/custom_prefab_pipeline/ESQUIRE_STOCK_VISUAL_CONTRACT.md)."""
        go = self.objs[self.container["units/" + key]].read_typetree()
        root = next(c["component"]["m_PathID"] for c in go["m_Component"]
                    if self.objs[c["component"]["m_PathID"]].type.name in ("Transform", "RectTransform"))
        tree = _Tree(self.objs, root)
        first = tree.children[root][0]
        authored = list(tree.local[first][2])
        if view_scale is not None:
            tree.local[first][2] = [float(np.copysign(view_scale, x)) for x in authored]
        anim, ctrl = None, None
        order = sorted(tree.names, key=lambda q: len(tree.subtree(q)), reverse=True)
        for p in order:
            for c in tree.comps[p]:
                if c.type.name != "Animator":
                    continue
                ref = c.read_typetree()["m_Controller"]
                o = self.objs.get(ref["m_PathID"]) if ref["m_FileID"] == 0 else None
                if o is not None and o.type.name == "AnimatorOverrideController":
                    anim, ctrl = p, ref
                    break
            if anim is not None:
                break
        if anim is None:
            raise ValueError(f"{key}: no Animator with an AnimatorOverrideController")
        u = _unit(key, self.objs, tree, root, anim, ctrl, None, clip_hz, want_clips)
        u.extra["authoredFirstChildScale"] = abs(float(authored[1]))
        u.extra["facingNode"] = first
        return u
