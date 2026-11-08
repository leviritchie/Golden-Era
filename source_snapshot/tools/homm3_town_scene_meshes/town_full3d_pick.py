#!/usr/bin/env python3
"""Building picking on the full-3D town scenes: what the pointer hits against what the player sees.

    python tools/homm3_town_scene_meshes/town_full3d_pick.py [--faction rampart ...] [--model box mesh] [--json OUT]

In game a building is hovered / clicked through the native EventSystem: PhysicsRaycaster -> nearest Collider ->
ExecuteEvents bubbles up the transform parents to the BhBuilding (IPointerEnterHandler / IPointerClickHandler,
mono decomp `Hex.Session.City.BhBuilding`). So the building that reacts at a pixel is the owner of the nearest
collider on that pixel's camera ray, and the building the player sees there is the nearest drawn surface.

Three pick models are measured against the visible id buffer:
  box  - the pre-2026-10-01 runtime: each active BhBuilding keeps ONE native BoxCollider, refit every reposition to
         the world AABB of the layer body's renderer bounds re-boxed in the collider's (rotated, scaled) space
         (Homm3FactoryCityWorldVisuals.TryAlignNativeColliderWithArt / CalculateMeshBoundsInColliderSpace);
         lower variants' colliders disabled; Walls variants ship no BoxCollider at all (cityHuman2 level67).
  mesh - building MeshColliders only (Homm3TownScene3dPick holders, before the occluders): one MeshCollider per
         drawn Mesh_ body renderer of the active layer, the renderer's own mesh at its world pose, parented under the
         BhBuilding; a variant without a native BoxCollider (vanilla never makes it clickable) only occludes, so it
         is scored as an occluder in both buffers; environment pieces pick nothing and hide nothing. Physics raycasts
         ignore back faces (Physics.queriesHitBackfaces default false), the same faces Hex/Lit Cull Back drops, so
         this model is the building-only z-buffer; what it gets wrong is building surface hidden by scenery.
  occluded - the shipped runtime: `mesh` plus an occluder MeshCollider on every environment Mesh_ renderer, on a
         layer the PhysicsRaycaster does not see, and the PhysicsRaycaster.Raycast postfix that drops hits beyond
         the nearest occluder. With the drawn set and the collider set the same pieces it equals the visible buffer
         by construction; the gate is that every drawn piece resolves, is Read/Write and is in both sets.
Visible: the active layers' Mesh_ body pieces plus every environment Mesh_ piece (terrain, near rocks, props,
houses) with Unity Cull Back (GL cull_face "front", see town_full3d_cull.py). Sky_ and Fx_ pieces are not counted:
the sky is background, Fx_ are transparent sprite / particle effects without depth.

Camera poses: the native cityHuman2 pan (conflux_town_camera_pan.poses: rest, cursor yaw/pitch extremes, the
look-at-pivot sweep and its transitions, sampled) under the catalog's framing (zoom, aimRotation, panScale), 16:9.
Pixels under the HUD (town_full3d_framing HUD_*) are excluded: the HUD canvas takes them first.
Town states: for every k, each native slot at min(k, its top level), so every reachable layer is measured.

Per building: IoU of hit vs visible pixels, recall (visible px that hit it) and precision (hit px that show it),
summed over poses. Proof tier: generated artifact (offline geometry of the installed bundle + level67 colliders);
the in-game pick is runtime-unproven until exercised.
"""
from __future__ import annotations

import argparse
import collections
import copy
import hashlib
import json
import math
import re
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import conflux_town_camera_pan as PAN  # noqa: E402

PLUGIN = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
SCENE3D = PLUGIN / "homm3_town_scene_meshes" / "scene3d"
REFS = PLUGIN / "homm3_runtime_assets" / "town_scene_refs"
GAME_DATA = Path(r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/HeroesOldenEra_Data")
CACHE = ROOT / ".cache" / "town_full3d_pick"
LEVEL = "level67"
MANAGER = "human_city_all_objects"   # the BhBuildingsManager GameObject (export_stock_city_scene.MANAGER)            # cityHuman2: the cityFactory city world loads it additively (Homm3FactoryCitySceneRegistrar)
REST_FOV = 47.6
W, H = 640, 360
HUD_RIGHT, HUD_BOTTOM, HUD_TOP = 0.90, 0.764, 0.03   # town_full3d_framing (measured on the user's capture)
NEAR, FAR = 0.05, 400.0
SWEEP_STRIDE = 40            # every 40th sampled pan pose besides the named proof poses (56 poses on cityHuman2)
OCC = 1000                   # visible-id of environment occluders
SCHEMA = "town_full3d_pick.v1"

# Homm3FactoryCityWorldVisuals.BuildingSidBySceneSlot
SID_BY_SLOT = {
    "Main": "Build_Main", "Tier_1": "Build_Tier_1", "Tier_2": "Build_Tier_2", "Tier_3": "Build_Tier_3",
    "Tier_4": "Build_Tier_4", "Tier_5": "Build_Tier_5", "Tier_6": "Build_Tier_6", "Tier_7": "Build_Tier_7",
    "Artifact_Market": "Build_Artifact_Market", "Golden_Calf": "Build_Golden_Calf", "Tavern": "Build_Tavern",
    "Magic_Guild": "Build_Magic_Guild", "Treasury": "Build_Treasury", "Bank": "Build_Bank", "Market": "Build_Market",
    "Walls": "Build_Wall", "Resource_Depot": "Build_Resource_Depot", "Resource_Depot_2": "Build_Resource_Depot_level_2",
}
# Slot children that are scenery, not BhBuilding variants (no collider, no level; the Market's variant is H_build_Merchant).
NOT_VARIANTS = {"market_elements"}
LEVEL_SUFFIX = re.compile(r"_Level_(\d+)$", re.IGNORECASE)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def trs(t) -> np.ndarray:
    p, q, s = t.m_LocalPosition, t.m_LocalRotation, t.m_LocalScale
    m = np.eye(4)
    m[:3, :3] = PAN.quat_to_mat([q.x, q.y, q.z, q.w]) * np.array([s.x, s.y, s.z])
    m[:3, 3] = [p.x, p.y, p.z]
    return m


# ---------------------------------------------------------------- native buildings (level67, read-only UnityPy)
def native_buildings() -> list[dict]:
    """Every BhBuilding variant under a known scene slot: slot, name, world matrix, BoxColliders (component order)."""
    src = GAME_DATA / LEVEL
    key = sha256(src)[:16]
    cache = CACHE / f"native_{LEVEL}_{key}.json"
    if cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))
    import UnityPy
    env = UnityPy.load(str(src), str(GAME_DATA / "sharedassets67.assets"), str(GAME_DATA / "globalgamemanagers.assets"))
    objs = {o.path_id: o for o in env.objects if o.assets_file.name == LEVEL}
    # IL2CPP MonoBehaviours carry no type tree here, so a variant is found by the native graph instead: a direct
    # child of a scene-slot GameObject under the BhBuildingsManager object (FindSceneSlot walks the same parents).
    out = []
    for o in objs.values():
        if o.type.name != "Transform":
            continue
        tr = o.read()
        if not tr.m_Father.path_id:
            continue
        slot_tr = tr.m_Father.read()
        slot = slot_tr.m_GameObject.read().m_Name
        if slot not in SID_BY_SLOT or not slot_tr.m_Father.path_id:
            continue
        if slot_tr.m_Father.read().m_GameObject.read().m_Name != MANAGER:
            continue
        go = tr.m_GameObject.read()
        boxes = []
        for c in go.m_Components:
            ref = getattr(c, "component", c)
            co = objs.get(ref.path_id)
            if co is not None and co.type.name == "BoxCollider":
                b = co.read()
                boxes.append({"enabled": bool(b.m_Enabled), "center": [b.m_Center.x, b.m_Center.y, b.m_Center.z],
                              "size": [b.m_Size.x, b.m_Size.y, b.m_Size.z]})
        m = trs(tr)
        cur = tr
        while cur.m_Father.path_id:
            cur = cur.m_Father.read()
            m = trs(cur) @ m
        out.append({"slot": slot, "name": go.m_Name, "world": m.tolist(), "boxes": boxes})
    out.sort(key=lambda r: (r["slot"], r["name"]))
    CACHE.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out), encoding="utf-8")
    return out


def variant_level(row: dict, levels_by_sid: dict) -> int | None:
    m = LEVEL_SUFFIX.search(row["name"])
    if m:
        return int(m.group(1))
    lv = levels_by_sid.get(SID_BY_SLOT[row["slot"]])
    if lv is not None and set(lv) == {1}:     # ResolveBuildingLevelOrThrow: Castle single-variant slot
        return 1
    return None


def resolve_layer(levels: dict, level: int) -> str | None:
    """TryResolveExactLayerId: exact level, else the highest mapped level below it."""
    if level in levels:
        return levels[level]
    below = [k for k in levels if k <= level]
    return levels[max(below)] if below else None


# ---------------------------------------------------------------- installed bundle geometry
def bundle_pieces(fdir: Path, catalog: dict) -> dict:
    """{prefabKey: [{"piece", "cls", "v"(root-frame float32 Nx3), "t"(int32 Mx3), "aabbW"(local AABB corners in
    root frame, 8x3)}]} for every MeshRenderer of every prefab (skinned / particle renderers are Fx, skipped)."""
    bundle = fdir / catalog["bundle"]
    key = catalog.get("bundleSha256") or sha256(bundle)
    cache = CACHE / f"{fdir.name}_{key[:16]}_v2.npz"
    if cache.is_file():
        z = np.load(cache, allow_pickle=False)
        index = json.loads(str(z["index"]))
        out = collections.defaultdict(list)
        for i, row in enumerate(index):
            out[row["prefab"]].append({"piece": row["piece"], "cls": row["cls"], "v": z[f"v{i}"], "t": z[f"t{i}"],
                                       "aabbW": z[f"a{i}"], "readable": row["readable"], "mesh": row["mesh"]})
        return dict(out)
    import UnityPy
    from UnityPy.helpers.MeshHelper import MeshHandler
    env = UnityPy.load(str(bundle))
    objs = {o.path_id: o for o in env.objects}
    prefab_by_go = {}
    for o in env.objects:
        if o.type.name == "AssetBundle":
            for path, info in o.read().m_Container:
                prefab_by_go[info.asset.path_id] = Path(path).stem
    rows, arrays = [], {}
    mesh_cache = {}
    for o in env.objects:
        if o.type.name != "MeshFilter":
            continue
        mf = o.read()
        go = mf.m_GameObject.read()
        if not mf.m_Mesh.path_id:
            continue
        comps = {}
        for c in go.m_Components:
            ref = getattr(c, "component", c)
            co = objs.get(ref.path_id)
            if co is not None:
                comps[co.type.name] = co
        if "MeshRenderer" not in comps:
            continue
        tr = comps["Transform"].read()
        chain = [tr]
        while chain[-1].m_Father.path_id:
            chain.append(chain[-1].m_Father.read())
        root_go_id = chain[-1].m_GameObject.path_id
        prefab = prefab_by_go.get(root_go_id)
        if prefab is None or len(chain) < 2:
            continue
        piece = chain[-2].m_GameObject.read().m_Name          # the prefab root's child the runtime classifies
        m = np.eye(4)
        for t in chain[:-1]:                                  # the instance root is seated at identity
            m = trs(t) @ m
        mid = mf.m_Mesh.path_id
        if mid not in mesh_cache:
            mesh = mf.m_Mesh.read()
            h = MeshHandler(mesh)
            h.process()
            v = np.asarray(h.m_Vertices, np.float32).reshape(-1, 3)
            t = np.concatenate([np.asarray(s, np.int32).reshape(-1, 3) for s in h.get_triangles()], 0)
            c, e = mesh.m_LocalAABB.m_Center, mesh.m_LocalAABB.m_Extent
            mesh_cache[mid] = (v, t, np.array([c.x, c.y, c.z]), np.array([e.x, e.y, e.z]),
                               bool(getattr(mesh, "m_IsReadable", False)), mesh.m_Name)
        v, t, c, e, readable, mesh_name = mesh_cache[mid]
        corners = c + e * np.array([[sx, sy, sz] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)])
        vw = (v.astype(np.float64) @ m[:3, :3].T + m[:3, 3]).astype(np.float32)
        aw = corners @ m[:3, :3].T + m[:3, 3]
        cls = piece.split("_")[0] + "_"
        i = len(rows)
        rows.append({"prefab": prefab, "piece": piece, "cls": cls, "readable": readable, "mesh": mesh_name})
        arrays[f"v{i}"], arrays[f"t{i}"], arrays[f"a{i}"] = vw, t, aw
    CACHE.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache, index=json.dumps(rows), **arrays)
    return bundle_pieces(fdir, catalog)


# ---------------------------------------------------------------- cameras
def framed_cams(catalog: dict) -> dict:
    """Root-local cameras (pos, fwd, up, right, fov) for the proof poses and a sample of the whole pan."""
    fr = (catalog.get("referenceCamera") or {}).get("framing") or {}
    zoom = float(fr.get("zoom", 1.0))
    s = float(fr.get("panScale", 1.0))
    q = fr.get("aimRotation", [0, 0, 0, 1])
    delta = PAN.quat_to_mat(q)
    fov = math.degrees(2 * math.atan(math.tan(math.radians(REST_FOV) / 2) / zoom))
    c = copy.deepcopy(PAN.load())
    st = c["settings"]
    rest = np.asarray(c["camera"]["worldPos"], np.float64)
    st["deltaHorizontalAngle"] *= s
    st["deltaVerticalAngle"] *= s
    st["positionNodes"] = (rest + s * (np.asarray(st["positionNodes"]) - rest)).tolist()
    p0, R0 = PAN.root_frame(c)
    Di = delta.T
    out = {}

    def add(name, p, f, u):
        f, u = Di @ np.asarray(f), Di @ np.asarray(u)
        r = np.cross(u, f)
        out[name] = {"pos": Di @ np.asarray(p), "fwd": f, "up": u, "right": r / np.linalg.norm(r), "fov": fov}

    for p in PAN.proof_poses(c):
        add(p["name"], p["pos"], p["fwd"], p["up"])
    for i, p in enumerate(PAN.poses(c)):
        if i % SWEEP_STRIDE or p["mode"] == "default":
            continue
        B = R0.T @ p["R"]
        add(f"pan{i:03d}_{p['mode'].replace('/', '-')}", R0.T @ (p["p"] - p0), B[:, 2], B[:, 1])
    return out, (p0, R0 @ delta)


def hud_mask() -> np.ndarray:
    xs = (np.arange(W) + 0.5) / W
    ys = (np.arange(H) + 0.5) / H
    return (xs[None, :] < HUD_RIGHT) & (ys[:, None] >= HUD_TOP) & (ys[:, None] < HUD_BOTTOM)


def pixel_rays(cam: dict):
    """Root-local ray origins (camera) and directions per pixel centre, H x W x 3."""
    ty = math.tan(math.radians(cam["fov"]) / 2)
    tx = ty * W / H
    xs = ((np.arange(W) + 0.5) / W * 2 - 1) * tx
    ys = (1 - (np.arange(H) + 0.5) / H * 2) * ty
    d = (xs[None, :, None] * cam["right"] + ys[:, None, None] * cam["up"] + cam["fwd"])
    return np.asarray(cam["pos"], np.float64), d


# ---------------------------------------------------------------- id renders
class IdRenderer:
    VS = """#version 330
uniform mat4 mvp; in vec3 in_pos; void main(){ gl_Position = mvp * vec4(in_pos, 1.0); }"""
    FS = """#version 330
uniform int pid; out vec4 o; void main(){ o = vec4(float(pid), 0, 0, 1); }"""

    def __init__(self):
        import moderngl
        self.mgl = moderngl
        self.ctx = moderngl.create_standalone_context()
        self.prog = self.ctx.program(vertex_shader=self.VS, fragment_shader=self.FS)
        self.fbo = self.ctx.simple_framebuffer((W, H), components=4, dtype="f4")
        self.vaos = {}

    def vao(self, key, v, t):
        if key not in self.vaos:
            self.vaos[key] = self.ctx.vertex_array(self.prog, [(self.ctx.buffer(np.ascontiguousarray(v, np.float32).tobytes()), "3f", "in_pos")],
                                                   self.ctx.buffer(np.ascontiguousarray(t, np.int32).tobytes()))
        return self.vaos[key]

    def render(self, cam: dict, items) -> np.ndarray:
        """items: [(key, v, t, id)]. Returns an H x W int id buffer (0 = nothing drawn), Unity Cull Back."""
        import stronghold_full3d_preview as PV
        mvp = PV.perspective(cam["fov"], W / H, NEAR, FAR) @ PV.view(cam["pos"], cam["fwd"], cam["up"], cam["right"])
        self.fbo.use()
        self.ctx.clear(0, 0, 0, 0)
        self.ctx.enable(self.mgl.DEPTH_TEST)
        self.ctx.enable(self.mgl.CULL_FACE)
        self.ctx.cull_face = "front"          # = Unity Cull Back (town_full3d_cull.py handedness note)
        self.prog["mvp"].write(mvp.T.astype(np.float32).tobytes())
        for key, v, t, pid in items:
            self.prog["pid"].value = int(pid)
            self.vao(key, v, t).render()
        a = np.frombuffer(self.fbo.read(components=4, dtype="f4"), np.float32).reshape(H, W, 4)[::-1, :, 0]
        return np.rint(a).astype(np.int32)

    def reset(self):
        """Drop the cached geometry: keys are only unique within one town."""
        for vao in self.vaos.values():
            vao.release()
        self.vaos = {}

    def release(self):
        self.ctx.release()


# ---------------------------------------------------------------- the legacy box model
def legacy_box(body_aabbs_root: list[np.ndarray], native: dict, root_to_world) -> dict | None:
    """The BoxCollider TryAlignNativeColliderWithArt fits, as (M collider->root, center, size) in collider space."""
    if not native["boxes"]:
        return None                                       # no native BoxCollider: nothing to align, no pick
    p0, Rw = root_to_world
    pts_w = np.concatenate(body_aabbs_root, 0) @ Rw.T + p0
    # Renderer.bounds is the world AABB of each renderer's transformed local AABB; encapsulated over the body.
    lo, hi = pts_w.min(0), pts_w.max(0)
    Mb = np.asarray(native["world"], np.float64).copy()
    Mb[:3, 3] = (lo + hi) / 2                            # AnchorBuildingToScene3dBody: position only
    corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    inv = np.linalg.inv(Mb)
    loc = corners @ inv[:3, :3].T + inv[:3, 3]
    clo, chi = loc.min(0), loc.max(0)
    center, size = (clo + chi) / 2, chi - clo
    lossy_z = np.linalg.norm(Mb[:3, 2])
    size[2] = max(size[2], 0.35 / (lossy_z if lossy_z >= 1e-4 else 1.0))
    # collider space -> root-local
    world_to_root = np.eye(4)
    world_to_root[:3, :3] = Rw.T
    world_to_root[:3, 3] = -Rw.T @ p0
    return {"M": world_to_root @ Mb, "center": center, "size": size}


def ray_boxes(origin: np.ndarray, dirs: np.ndarray, boxes: list[tuple[int, dict]]) -> np.ndarray:
    """Nearest box hit per pixel (PhysicsRaycaster: sorted by distance; a ray starting inside a box misses it)."""
    best_t = np.full(dirs.shape[:2], np.inf)
    best = np.zeros(dirs.shape[:2], np.int32)
    for bid, b in boxes:
        inv = np.linalg.inv(b["M"])
        o = inv[:3, :3] @ origin + inv[:3, 3] - b["center"]
        d = dirs @ inv[:3, :3].T
        half = b["size"] / 2
        if np.all(np.abs(o) <= half):
            continue
        with np.errstate(divide="ignore", invalid="ignore"):
            t1 = (-half - o) / d
            t2 = (half - o) / d
        tmin = np.nanmax(np.minimum(t1, t2), -1)
        tmax = np.nanmin(np.maximum(t1, t2), -1)
        hit = (tmax >= tmin) & (tmin > 0)
        better = hit & (tmin < best_t)
        best_t[better] = tmin[better]
        best[better] = bid
    return best


# ---------------------------------------------------------------- measurement
def town_states(variants: list[dict]) -> list[dict]:
    """[{slot: variant}] for k = 1..max level: each slot at min(k, its top level)."""
    by_slot = collections.defaultdict(list)
    for v in variants:
        by_slot[v["slot"]].append(v)
    top = max(v["level"] for v in variants)
    states = []
    for k in range(1, top + 1):
        st = {}
        for slot, vs in by_slot.items():
            vs = sorted(vs, key=lambda r: r["level"])
            pick = [r for r in vs if r["level"] <= k]
            st[slot] = pick[-1] if pick else vs[0]
        states.append(st)
    uniq, seen = [], set()
    for st in states:
        sig = tuple(sorted((s, v["layerId"]) for s, v in st.items()))
        if sig not in seen:
            seen.add(sig)
            uniq.append(st)
    return uniq


MODELS = ("box", "mesh", "occluded")


def measure_faction(fdir: Path, models=MODELS, renderer: IdRenderer | None = None) -> dict:
    catalog = json.loads((fdir / "catalog.json").read_text(encoding="utf-8"))
    fraction = catalog["fraction"]
    if not catalog.get("fullScene3d"):
        raise SystemExit(f"{fraction}: not a full-3D catalog")
    lmap = json.loads((REFS / fraction / "layers" / "building_layer_map.json").read_text(encoding="utf-8"))
    levels_by_sid = {sid: {int(k): v for k, v in lv.items()} for sid, lv in lmap["nativeLevels"].items()}
    prefab_by_layer = {l["layerId"]: l["prefabKey"].lower() for l in catalog["layers"]}
    # Unity AssetBundle.LoadAsset matches names case-insensitively; the container stems may be lower case.
    pieces = {k.lower(): v for k, v in bundle_pieces(fdir, catalog).items()}
    env_key = catalog["environment"]["prefabKey"].lower()
    errors = []                                          # what the runtime would refuse (it throws on each)
    if env_key not in pieces:
        errors.append(f"environment prefab {env_key!r} not in the bundle")
    env_body = [p for p in pieces.get(env_key, []) if p["cls"] == "Mesh_"]
    if not env_body:
        errors.append("environment has no Mesh_ renderer (no occluders)")
    env_items = [(f"{fraction}/env/{i}", p["v"], p["t"], OCC) for i, p in enumerate(env_body)]
    for prefab in {env_key, *prefab_by_layer.values()}:
        for p in pieces.get(prefab, []):
            if p["cls"] == "Mesh_" and not p["readable"]:
                errors.append(f"{prefab}/{p['piece']}: mesh {p['mesh']!r} is not Read/Write (no runtime MeshCollider)")

    variants = []
    for row in native_buildings():
        sid = SID_BY_SLOT[row["slot"]]
        if sid not in levels_by_sid:
            continue                                     # the town has no art for this slot: never activated
        if row["name"] in NOT_VARIANTS:
            continue
        level = variant_level(row, levels_by_sid)
        if level is None:
            continue
        layer = resolve_layer(levels_by_sid[sid], level)
        if layer is None:
            continue
        if layer not in prefab_by_layer:
            errors.append(f"{row['slot']}:{row['name']} -> layer {layer!r} has no catalog prefab")
            continue
        if prefab_by_layer[layer] not in pieces:
            errors.append(f"layer {layer!r}: prefab {prefab_by_layer[layer]!r} not in the bundle")
            continue
        if not any(p["cls"] == "Mesh_" for p in pieces[prefab_by_layer[layer]]):
            errors.append(f"layer {layer!r}: prefab has no Mesh_ body renderer to pick")
            continue
        variants.append({**row, "level": level, "layerId": layer, "prefab": prefab_by_layer[layer]})
    cams, root_to_world = framed_cams(catalog)
    hud = hud_mask()
    own = renderer is None
    rd = renderer or IdRenderer()
    rd.reset()                                           # a shared renderer must not reuse another town's meshes
    agg = {m: collections.defaultdict(lambda: np.zeros(3, np.int64)) for m in models}   # [inter, visible, hit]
    pose_rows = {m: {} for m in models}
    misc = collections.Counter()
    try:
        for si, state in enumerate(town_states(variants)):
            ids = {}                                     # building index -> label
            vis_items, mesh_items, boxes = [], [], []
            for bi, (slot, var) in enumerate(sorted(state.items())):
                bid = bi + 1
                label = f"{slot}:{var['layerId']}"
                interactive = bool(var["boxes"])
                if interactive:
                    ids[bid] = label
                else:
                    misc[f"nonInteractive:{label}"] += 1
                # A variant without a native BoxCollider is not clickable in vanilla either: drawn, it occludes like
                # scenery (visible OCC), and the runtime gives it occluders (hit OCC).
                vid = bid if interactive else OCC
                body = [p for p in pieces[var["prefab"]] if p["cls"] == "Mesh_"]
                for j, p in enumerate(body):
                    item = (f"{fraction}/{var['prefab']}/{j}", p["v"], p["t"], vid)
                    vis_items.append(item)
                    mesh_items.append(item)
                if "box" in models:
                    b = legacy_box([p["aabbW"] for p in body], var, root_to_world)
                    if b is not None:
                        boxes.append((bid, b))
            for pname, cam in cams.items():
                vis = rd.render(cam, vis_items + env_items)
                vis_b = np.where((vis > 0) & (vis < OCC), vis, 0)
                hits = {}
                if "mesh" in models:
                    m_hit = rd.render(cam, mesh_items)
                    hits["mesh"] = np.where(m_hit == OCC, 0, m_hit)
                if "occluded" in models:
                    o_hit = rd.render(cam, mesh_items + env_items)
                    hits["occluded"] = np.where(o_hit >= OCC, 0, o_hit)
                if "box" in models:
                    o, d = pixel_rays(cam)
                    hits["box"] = ray_boxes(o, d, boxes)
                for m, hit in hits.items():
                    hv, vv = hit[hud], vis_b[hud]
                    wrong = int(((hv != vv) & ((hv > 0) | (vv > 0))).sum())
                    any_b = int(((hv > 0) | (vv > 0)).sum())
                    pr = pose_rows[m].setdefault(pname, [0, 0])
                    pr[0] += wrong
                    pr[1] += any_b
                    for bid, label in ids.items():
                        a, b = vv == bid, hv == bid
                        agg[m][label] += [int((a & b).sum()), int(a.sum()), int(b.sum())]
    finally:
        if own:
            rd.release()
    out = {"schema": SCHEMA, "fraction": fraction, "bundleSha256": catalog.get("bundleSha256"),
           "raster": [W, H], "poses": len(cams), "states": len(town_states(variants)), "notes": dict(misc),
           "errors": sorted(set(errors)), "models": {}}
    for m in models:
        rows = {}
        for label, (i, v, h) in sorted(agg[m].items()):
            u = v + h - i
            rows[label] = {"iou": round(i / u, 4) if u else 1.0, "recall": round(i / v, 4) if v else None,
                           "precision": round(i / h, 4) if h else None, "visiblePx": int(v), "hitPx": int(h)}
        wrong = sum(r[0] for r in pose_rows[m].values())
        anyb = sum(r[1] for r in pose_rows[m].values())
        worst = max(pose_rows[m].items(), key=lambda kv: kv[1][0] / max(kv[1][1], 1))
        out["models"][m] = {"pixelAgreement": round(1 - wrong / anyb, 4) if anyb else 1.0,
                            "worstPose": [worst[0], round(1 - worst[1][0] / max(worst[1][1], 1), 4)],
                            "buildings": rows}
    return out


def installed_dirs(factions=None) -> list[Path]:
    out = []
    for d in sorted(SCENE3D.iterdir()):
        if not (d / "catalog.json").is_file():
            continue
        if factions and d.name.replace("homm3_", "") not in factions and d.name not in factions:
            continue
        c = json.loads((d / "catalog.json").read_text(encoding="utf-8"))
        if c.get("fullScene3d"):
            out.append(d)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--faction", nargs="*")
    ap.add_argument("--model", nargs="*", default=list(MODELS), choices=list(MODELS))
    ap.add_argument("--json")
    a = ap.parse_args()
    res = {}
    rd = IdRenderer()
    try:
        for d in installed_dirs(a.faction):
            r = measure_faction(d, tuple(a.model), rd)
            res[r["fraction"]] = r
            for m, mr in r["models"].items():
                low = sorted(mr["buildings"].items(), key=lambda kv: kv[1]["iou"])[:3]
                print(f"{r['fraction']:18s} {m:4s} pixelAgreement={mr['pixelAgreement']:.4f} worst={mr['worstPose']} "
                      f"lowestIoU={[(k, v['iou']) for k, v in low]}")
            if r["notes"]:
                print("   notes:", r["notes"])
            for e in r["errors"]:
                print("   ERROR:", e)
    finally:
        rd.release()
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
