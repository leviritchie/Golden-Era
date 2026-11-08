#!/usr/bin/env python3
"""Rampart + Dungeon: Meshy T2 building meshes in the full-3D town lane (artifacts/meshy_town_scene_meshes/_BRIEF_t2_towns.md).
The faction comes from TOWN_FULL3D_FACTION; its layers, reverts, tunes, seed and build states are one FACTIONS entry
below (Dungeon joined 2026-09-29: same method and gates, docs/homm3_dungeon_t2_town_buildings.md).

    set TOWN_FULL3D_FACTION=rampart & set TOWN_FULL3D_CANDIDATE=t2_v1
    python tools/homm3_town_scene_meshes/rampart_t2_buildings.py fit   [--only a,b]   # register, no staging
    python tools/homm3_town_scene_meshes/rampart_t2_buildings.py stage [--only a,b]   # every layer not in BROKEN
    python tools/homm3_town_scene_meshes/rampart_t2_buildings.py revert               # BROKEN -> seed relief
    python tools/homm3_town_scene_meshes/rampart_t2_buildings.py fx                   # seed fx onto the T2 bodies
    python tools/homm3_town_scene_meshes/rampart_t2_buildings.py finish               # walls, catalog, cull gate
    then stronghold_full3d_scene.py bundle / render / validate (docs/homm3_rampart_t2_town_buildings.md).

Per layer (MESH_SOURCE below; every layer on its T2 body unless BROKEN, user decision 2026-09-29):
1. Registration under the lane's rest camera (RectFitter: yaw, scale, ground contact, x/y stretch) on the lane's
   frame depth, then depth_slide (scale about the camera, rest projection unchanged) until the terrain does not
   hide the body; triangles with a corner outside the painted rect at rest are dropped (the framing gate).
2. Screen-space split (subdivide_screen): faces the rest camera draws are midpoint-split to <= SUBDIV_PX.
3. Painted front (stage_split -> town_full3d_t2_paint.painted_split, the one T2 bake): faces seen at rest ->
   Mesh_Body_<layer>, uv = their rest px in a SUPER crop of the sprite, de-lit and shaded through the smooth view
   normal; every other face -> Mesh_BodyM_<layer> with the Meshy texture gain-matched to the de-lit painting. Both
   two-sided (the game culls back faces; T2 meshes are open).
4. Residual: sprite px the body leaves uncovered at rest keep the seed's (wall_v4) front triangles there as
   Mesh_BodyRest_<layer> with the seed's texture (residual() below), so no px of the painting disappears at rest.
Proof tier: generated artifact (offline fit + stage); the Unity editor render re-measures independently.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stronghold_full3d_common as SC  # noqa: E402
import stronghold_full3d_ground as G  # noqa: E402
import stronghold_full3d_terrain as T  # noqa: E402
import stronghold_full3d_scene as S  # noqa: E402
import fit_mesh_to_sprite as FIT  # noqa: E402
import town_full3d_t2_paint as TP  # noqa: E402  (the one T2 bake)

def _rampart() -> dict:
    # layer -> Meshy output folder (relative to MESHY). tbrmdw_5_2 = tbrmdw_5 + two small lanterns: same mesh, own paint.
    MESH_SOURCE = {l: f"{l}/t2_a1" for l in (
        "tbrmhall", "tbrmhal2", "tbrmhal3", "tbrmcstl", "tbrmcas2", "tbrmcas3",
        "tbrmmage", "tbrmmag2", "tbrmmag3", "tbrmmag4", "tbrmtvrn", "tbrmmark", "tbrmsilo", "tbrmblak",
        "tbrmspec", "tbrmext0", "tbrmhrd1", "tbrmholy",
        "tbrmdw_0", "tbrmdw_0_2", "tbrmdw_1", "tbrmdw_1_2", "tbrmdw_2", "tbrmdw_2_2", "tbrmdw_3", "tbrmdw_3_2",
        "tbrmdw_4", "tbrmdw_4_2", "tbrmdw_5", "tbrmdw_6", "tbrmdw_6_2")}
    MESH_SOURCE["tbrmdw_5_2"] = "tbrmdw_5/t2_a1"
    # a1 review: the dragon cliffs came back as a flat sheet (dw_6) and loose vertical strips (dw_6_2); c1 = concept step
    MESH_SOURCE["tbrmdw_6"] = "tbrmdw_6/t2_c1"
    MESH_SOURCE["tbrmdw_6_2"] = "tbrmdw_6_2/t2_c1"
    # the blacksmith sprite is a forest clump with a small hut; T2 modelled the hut alone, so the layer keeps its lane body
    del MESH_SOURCE["tbrmblak"]
    # per-layer overrides (fit options, mesh surgery), from review
    # Per-layer review (layer_sheet renders: env + one layer, seed wall_v4 vs T2, rest + sweep_left/right/high, the
    # lane's shading with Unity's back-face culling).
    # Layers that keep the installed relief: only a genuinely broken mesh (fragments, a flat slab, or the main feature
    # missing), judged by eye at the sweeps (user decision 2026-09-29; rest dE76 is a diagnostic, never a revert gate).
    BROKEN = {
        "tbrmdw_1": "the mound's left side is a flat bright Meshy ground slab at sweep_left",
        "tbrmdw_1_2": "as tbrmdw_1 (same flat slab)",
        "tbrmhrd1": "as tbrmdw_1: a flat bright ground slab beside the mound at sweep_left",
        "tbrmdw_0_2": "a flat green ground slab under the porch at sweep_high and sweep_left",
        "tbrmmark": "the stall comes apart into a dark box and loose fragments at every sweep",
    }
    # (a whole-face-outside-the-sprite cut was tried on these and on dw_0 / dw_2: it removes 3-39 faces and fixes none;
    # the slabs straddle the sprite outline)
    FIT_TUNE: dict = {
        # a1 put the waterfall rock inside a white cylindrical basin the sprite does not have: drop every face whose
        # centroid lies farther than dropRMin (model units, half-extent 0.5) from the rock's vertical axis
        "tbrmdw_3": {"dropRMin": 0.3},
        # the castle's Meshy hill plate runs past the sprite's hill on the left (a green wedge at the sweeps): faces seen
        # at rest wholly outside the sprite (dilated cutOvershootPx) are cut
        "tbrmcstl": {"cutOvershootPx": 6}, "tbrmcas2": {"cutOvershootPx": 6}, "tbrmcas3": {"cutOvershootPx": 6},
    }
    return {"meshSource": MESH_SOURCE, "broken": BROKEN, "fitTune": FIT_TUNE, "seed": "wall_v4",
            "gen": "rampart_t2_generate", "doc": "docs/homm3_rampart_t2_town_buildings.md", "states": {
        # one build state per preview (the lane stacks every layer's prefab; the game shows one level per slot)
        "max": ["tbrmcas3", "tbrmhal3", "tbrmmag4", "tbrmtvrn", "tbrmmark", "tbrmsilo", "tbrmblak", "tbrmspec",
                "tbrmext0", "tbrmhrd1", "tbrmholy", "tbrmdw_0_2", "tbrmdw_1_2", "tbrmdw_2_2", "tbrmdw_3_2",
                "tbrmdw_4_2", "tbrmdw_5_2", "tbrmdw_6_2"],
        "base": ["tbrmcstl", "tbrmhall", "tbrmmage", "tbrmtvrn", "tbrmdw_0", "tbrmdw_1", "tbrmdw_2", "tbrmdw_3",
                 "tbrmdw_4", "tbrmdw_5", "tbrmdw_6"],
        "mid": ["tbrmcas2", "tbrmhal2", "tbrmmag2", "tbrmmag3", "tbrmtvrn", "tbrmmark", "tbrmsilo", "tbrmblak",
                "tbrmdw_0", "tbrmdw_1", "tbrmdw_2", "tbrmdw_3", "tbrmdw_4", "tbrmdw_5", "tbrmdw_6"]}}


def _dungeon() -> dict:
    # 22 meshes, recipe t2_a1 (artifacts/meshy_town_scene_meshes/homm3_dungeon/HANDOFF.md); tbdnhrd2 (the warren's
    # horde sprite: more mushrooms) reuses tbdndw_0_2's mesh with its own painting. The cavern-wall pieces (dw_1, dw_3,
    # dw_5, dw_6 and their upgrades) and the ext0 sparkle ring were never meshed and keep the seed relief untouched.
    import dungeon_t2_generate as DG
    MESH_SOURCE = {l: f"{l}/t2_a1" for l in DG.MESH_LAYERS}
    MESH_SOURCE["tbdnhrd2"] = "tbdndw_0_2/t2_a1"
    # judged by eye at the sweeps (layer previews, Unity back-face culling); see docs/homm3_dungeon_t2_town_buildings.md
    BROKEN = {
        "tbdnsilo": "the sprite is a tiny frame-cut grain field; T2 made a flat white trough, which shows as a white "
                    "plank across the grain at every sweep (the heaps are missing)",
        "tbdnmark": "the stall row comes apart: its lower half is a separate floating slab of smeared paint at every "
                    "sweep",
    }
    FIT_TUNE: dict = {}
    return {"meshSource": MESH_SOURCE, "broken": BROKEN, "fitTune": FIT_TUNE, "seed": "wall_v7",
            "gen": "dungeon_t2_generate", "doc": "docs/homm3_dungeon_t2_town_buildings.md", "states": {
        "max": ["tbdncstl_3", "tbdnhall_3", "tbdnmage_4", "tbdntvrn", "tbdnmark", "tbdnsilo", "tbdnblak", "tbdnspec",
                "tbdnext0", "tbdnhrd2", "tbdnholy", "tbdndw_0_2", "tbdndw_1_2", "tbdndw_2_2", "tbdndw_3_2",
                "tbdndw_4_2", "tbdndw_5_2", "tbdndw_6_2"],
        "base": ["tbdncstl", "tbdnhall", "tbdnmage", "tbdntvrn", "tbdndw_0", "tbdndw_1", "tbdndw_2", "tbdndw_3",
                 "tbdndw_4", "tbdndw_5", "tbdndw_6"],
        "mid": ["tbdncstl_2", "tbdnhall_2", "tbdnmage_2", "tbdnmage_3", "tbdntvrn", "tbdnmark", "tbdnsilo",
                "tbdnblak", "tbdndw_0", "tbdndw_1", "tbdndw_2", "tbdndw_3", "tbdndw_4", "tbdndw_5", "tbdndw_6"]}}


FACTIONS = {"rampart": _rampart, "dungeon": _dungeon}
if SC.FACTION not in FACTIONS:
    raise SystemExit(f"rampart_t2_buildings: TOWN_FULL3D_FACTION={SC.FACTION} has no T2 entry (one of {sorted(FACTIONS)})")
W, H, TW, TH = SC.W, SC.H, SC.TW, SC.TH
CFG = FACTIONS[SC.FACTION]()
MESHY = SC.ROOT / "artifacts" / "meshy_town_scene_meshes" / f"homm3_{SC.FACTION}"
MESH_SOURCE, BROKEN, FIT_TUNE, STATES = CFG["meshSource"], CFG["broken"], CFG["fitTune"], CFG["states"]
STAGE_ONLY_TUNE = ("cutOvershootPx", "cutOutsidePx")   # stage-time cuts: changing them never re-runs the fit


def _fit_tune(t):
    return {k: v for k, v in (t or {}).items() if k not in STAGE_ONLY_TUNE} or None


                             # Low on purpose: at rest the projection is exact whatever the facing, and T2's organic
                             # parts (canopies, rock) carry normals far from the view on surfaces the rest camera
                             # sees (tbrmdw_4_2 at 0.12-0.30: 21% of rest-visible texels painted, white Meshy leaves)
SUPER = TP.SUPER             # z-buffer / sprite sampling resolution, x the 1920x1080 frame
WORK = S.WORK / "t2"


# ------------------------------------------------------------------------------------------------ inputs
def load_glb(path: Path) -> dict:
    import trimesh
    sc = trimesh.load(str(path), force="scene")
    geos = list(sc.geometry.values())
    if len(geos) != 1:
        raise SystemExit(f"{path}: {len(geos)} geometries (expected one Meshy mesh)")
    m = sc.dump(concatenate=True) if len(sc.graph.nodes_geometry) != 1 else None
    g = geos[0]
    tf = sc.graph[sc.graph.nodes_geometry[0]][0]
    if not np.allclose(tf, np.eye(4)):
        raise SystemExit(f"{path}: node transform is not identity")
    del m
    v = np.asarray(g.vertices, np.float64).copy()
    n = np.asarray(g.vertex_normals, np.float64).copy()
    uv = np.asarray(g.visual.uv, np.float64).copy()
    tex = g.visual.material.baseColorTexture
    if tex is None:
        raise SystemExit(f"{path}: no base colour texture")
    v[:, 0] *= -1.0          # glTF right-handed -> Unity left-handed (glTFast), as fit_mesh_to_sprite.load_glb_unity
    n[:, 0] *= -1.0
    return {"v": v, "n": n, "f": np.asarray(g.faces, np.int64), "uv": uv,
            "tex": np.asarray(tex.convert("RGB")).astype(np.float32) / 255.0}


def load_layer_mesh(lid: str, src: Path) -> dict:
    g = load_glb(src)
    r_min = FIT_TUNE.get(lid, {}).get("dropRMin")
    if r_min is not None:
        c = g["v"][g["f"]].mean(1)
        ax = np.median(c[:, [0, 2]], 0)
        keep = np.linalg.norm(c[:, [0, 2]] - ax, axis=1) < r_min
        used = np.unique(g["f"][keep])
        remap = np.full(len(g["v"]), -1)
        remap[used] = np.arange(len(used))
        g = {**g, "v": g["v"][used], "n": g["n"][used], "uv": g["uv"][used], "f": remap[g["f"][keep]],
             "dropped": int((~keep).sum())}
    return g


def target_mask(L: dict) -> np.ndarray:
    """Sprite alpha in the frame (x1.8, top-left), with the lane's own fringe drop (native_mask)."""
    import stronghold_full3d_buildings as BL
    m = BL.native_mask(L).astype(np.uint8) * 255
    big = cv2.resize(m, (round(m.shape[1] * SC.SCALE), round(m.shape[0] * SC.SCALE)), interpolation=cv2.INTER_LINEAR)
    out = np.zeros((H, W), np.uint8)
    x0, y0 = round(L["x"] * SC.SCALE), round(L["y"] * SC.SCALE)
    h, w = big.shape
    out[y0:y0 + h, x0:x0 + w] = big[:max(0, min(h, H - y0)), :max(0, min(w, W - x0))]
    out[:, TW:] = 0
    out[TH:, :] = 0
    return out


class RectFitter(FIT.Fitter):
    """Fitter with the frame outside the painted rect as don't-care (neither target nor silhouette counts there)."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        d = self.down
        ys, xs = np.mgrid[0:self.target.shape[0], 0:self.target.shape[1]]
        self.care = (xs * d < TW) & (ys * d < TH)
        self.care_w = self.care[self.win[1]:self.win[3], self.win[0]:self.win[2]]

    def silhouette(self, w, full=False):
        s = super().silhouette(w, full)
        return s & (self.care if full else self.care_w)


def frame_z(sc) -> np.ndarray:
    """Terrain camera z per frame px, rendered from the candidate's own staged environment bins (the terrain the
    bundle ships, whatever texture sources staged it), sky and effects excluded; empty px take the nearest value."""
    S.load_staged_preview(sc, {S.ENV_KEY})
    Ps, fs, off = [], [], 0
    for name, P, n, uv, tris, img, unlit in sc.preview:
        if unlit or "/Mesh_" not in name:
            continue
        Ps.append(P)
        fs.append(np.asarray(tris) + off)
        off += len(P)
    sc.preview = []
    z = TP.zbuffer(sc.cam, np.concatenate(Ps), np.concatenate(fs))[0][::SUPER, ::SUPER]
    ok = np.isfinite(z)
    from scipy.ndimage import distance_transform_edt
    _, (iy, ix) = distance_transform_edt(~ok, return_indices=True)
    return z[iy, ix].astype(np.float64)


# ------------------------------------------------------------------------------------------------ fit
def fit_layer(sc, lid: str, zf: np.ndarray) -> dict:
    L = SC.layers()[lid]
    src = MESHY / MESH_SOURCE[lid] / "model.glb"
    g = load_layer_mesh(lid, src)
    tgt = target_mask(L)
    ys, xs = np.nonzero(tgt > 127)
    if len(xs) == 0:
        raise SystemExit(f"{lid}: empty target mask")
    tune = FIT_TUNE.get(lid, {})
    fit = RectFitter(sc.cam, zf, (W, H), tgt > 127, g["v"], g["f"], down=2)
    res = fit.fit((float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())),
                  yaws=tune.get("yaws", range(0, 360, 20)))
    if tune.get("stretch"):
        res = fit.refine_stretch(res, **tune["stretch"])
    sil = res.pop("silhouette")
    res.update({"layer": lid, "source": str(src.relative_to(SC.ROOT)).replace("\\", "/"), "modelHeight": fit.model_h})
    # world transform pieces for staging
    lo, hi = g["v"].min(0), g["v"].max(0)
    res["modelOffset"] = [float(-(lo[0] + hi[0]) / 2), float(-lo[1]), float(-(lo[2] + hi[2]) / 2)]
    WORK.mkdir(parents=True, exist_ok=True)
    vis = np.zeros((H // 2, W // 2, 3), np.uint8)
    t2 = fit.target
    vis[..., 1] = t2 * 160
    vis[..., 2] = sil * 200
    vis[..., 0] = (t2 & sil) * 255
    Image.fromarray(vis).save(WORK / f"fit_{lid}.png")
    return res


def world_mesh(g: dict, fr: dict) -> tuple[np.ndarray, np.ndarray]:
    k = float(fr.get("stretchY", 1.0))
    R = FIT.yaw_matrix(fr["yaw"])
    v0 = g["v"] + np.array(fr["modelOffset"])
    P = ((v0 * np.array([1.0, k, 1.0])) @ R.T) * fr["scale"] + np.array(fr["position"])
    n = (g["n"] / np.array([1.0, k, 1.0])) @ R.T
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    return P, n


# ------------------------------------------------------------------------------------------------ bake
SUBDIV_PX = 8.0              # rest-frame px: longer projected edges are split (TP.subdivide_screen max_px)


def stage_split(sc, lid: str, g: dict, P, n, f, zb, idb) -> dict:
    """Mesh_Body_<layer> (the faces seen at rest, painted in screen space) + Mesh_BodyM_<layer> (the rest, Meshy
    texture gain-matched): town_full3d_t2_paint.painted_split, the one T2 bake. This lane's by-design values: the
    sprite_fill mask is the fringe-dropped native_mask; the rest z-buffer is the one lean_normals already used; the
    Meshy gain is measured once more than 200 px are painted and kept float32; the bins carry no offline preview.
    (Replaces a bake into the Meshy atlas, which blurred thin T2 parts: hall rest dE76 6.7 against the seed's 1.5.)"""
    import stronghold_full3d_buildings as BL
    L = SC.layers()[lid]
    return TP.painted_split(sc, lid, L, BL.native_mask(L), P, n, f, g["uv"], G.SC_srgb_to_lin(g["tex"]),
                            f"Mesh_Body_{lid}", f"Mesh_BodyM_{lid}", meshy_max=2048, preview=False,
                            zbuf=(zb, idb), gain_guard=("px", 200), gain_dtype=np.float32)


def outward_faces(P: np.ndarray, n: np.ndarray, f: np.ndarray) -> tuple[np.ndarray, dict]:
    gn = np.cross(P[f[:, 1]] - P[f[:, 0]], P[f[:, 2]] - P[f[:, 0]])
    agree = (gn * n[f].mean(1)).sum(1)
    flip = agree < 0
    out = f.copy()
    out[flip] = out[flip][:, [0, 2, 1]]
    return out, {"flippedShare": round(float(flip.mean()), 4)}


def overshoot_faces(sc, lid: str, P: np.ndarray, f: np.ndarray, dil_px: int, seen_only: bool = True) -> np.ndarray:
    """Faces inside the painted rect whose three corners all project outside the sprite (dilated); seen_only keeps
    the cut to faces drawn at rest (a hidden face outside the silhouette is an invented part or slab that only the
    sweeps reveal, cut with seen_only=False)."""
    tgt = cv2.dilate((target_mask(SC.layers()[lid]) > 127).astype(np.uint8), np.ones((2 * dil_px + 1,) * 2, np.uint8))
    zb, idb = TP.zbuffer(sc.cam, P, f)
    seen = np.zeros(len(f), bool)
    seen[np.unique(idb[idb >= 0])] = True
    px, py, _ = T.project(sc.cam, P)
    xi, yi = np.clip(px.astype(int), 0, W - 1), np.clip(py.astype(int), 0, H - 1)
    out_v = (tgt[yi, xi] == 0) & (px < TW) & (py < TH) & (px >= 0) & (py >= 0)
    return (seen | (not seen_only)) & out_v[f].all(1)


def revert_to_seed(lids: list[str]) -> None:
    """Restore the seed's (wall_v4) Mesh_Body_<layer> bin, rows and stage-report entry for layers kept on the seed."""
    import shutil
    seed_stage = SEED / "unity_project" / S.ASSET_ROOT
    seed_rows = json.loads((seed_stage / "rows.json").read_text(encoding="utf-8"))
    seed_rep = json.loads((SEED / "work" / "stage_report.json").read_text(encoding="utf-8"))
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    rp = S.WORK / "stage_report.json"
    rep_all = json.loads(rp.read_text(encoding="utf-8"))
    for lid in lids:
        pk = S.PREFIX + lid
        for suf in (".bytes", "_albedo.png"):
            shutil.copyfile(seed_stage / pk / f"Mesh_Body_{lid}{suf}", S.STAGE / pk / f"Mesh_Body_{lid}{suf}")
        for stale in [*(S.STAGE / pk).glob("Mesh_BodyRest_*"), *(S.STAGE / pk).glob("Mesh_BodyM_*")]:
            stale.unlink()
        rows[pk] = seed_rows[pk]
        rep_all["buildings"][lid] = seed_rep["buildings"][lid]
        rep_all["buildings"][lid]["t2Review"] = "kept relief (broken mesh): " + BROKEN[lid]
    S.ROWS.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    rp.write_text(json.dumps(rep_all, indent=1), encoding="utf-8")


def finish(sc) -> int:
    """After stage / revert / fx: the seed's closing walls minus the T2 layers (a Meshy body has none, and the Unity
    rest-walls check must not look for them), the catalog plus its meshyBuildings record, the pan previews, and the
    lane's see-through gate (no worse than the installed baseline at any pose; exits non-zero otherwise)."""
    import importlib
    GEN = importlib.import_module(CFG["gen"])
    rp = S.WORK / "stage_report.json"
    old = json.loads(rp.read_text(encoding="utf-8"))
    t2 = sorted(l for l, r in old.get("buildings", {}).items() if r.get("kind") == "meshy_t2")
    old["meshyT2"] = {"layers": t2, "keptRelief": BROKEN,
                      "method": "Meshy T2 mesh fitted to the sprite; painted front (faces seen at rest take the sprite "
                                "by screen position, de-lit through the smooth view normal) + Meshy remainder"}
    rp.write_text(json.dumps(old, indent=1), encoding="utf-8")
    edges = {k: v for k, v in dict(np.load(SEED / "work" / "closing_walls.npz")).items() if k not in t2}
    np.savez(S.WORK / "closing_walls.npz", **edges)
    S.write_catalog(sc, carry="fresh")
    cp = S.OUT / "catalog.json"
    cat = json.loads(cp.read_text(encoding="utf-8"))
    calls = [json.loads(x) for x in GEN.LEDGER.read_text(encoding="utf-8").splitlines() if x.strip()]
    calls = [c for c in calls if c.get("faction") == GEN.FACTION]
    cat["meshyBuildings"] = {
        "method": old["meshyT2"]["method"] + f"; two-sided; seed relief residual ({SEED.name}) on uncovered sprite px",
        "layers": t2, "keptRelief": sorted(BROKEN), "meshyCredits": GEN.spent(), "ledgerCalls": len(calls),
        "doc": CFG["doc"]}
    cp.write_text(json.dumps(cat, indent=1) + chr(10), encoding="utf-8")
    S.load_staged_preview(sc)
    print(S.preview(sc, S.WORK / "preview", {"default": sc.cam, **S.pan_cams(sc)}))
    st = S.see_through_report(sc)
    (S.WORK / "see_through.json").write_text(json.dumps(st, indent=1), encoding="utf-8")
    old = json.loads(rp.read_text(encoding="utf-8"))
    old["seeThrough"] = {k: st[k] for k in ("metric", "totalPx", "mode", "baseline", "worse")}
    rp.write_text(json.dumps(old, indent=1), encoding="utf-8")
    print(json.dumps({"seeThrough": old["seeThrough"]}))
    S.cull_gate_or_exit(st)
    return 0


FX_WATER_EPS = 0.002        # water sits this share of camera depth in front of the T2 surface it lies on
FX_PARTICLE_EPS = 0.01       # particle emitters (flames, glows) this share in front


def fx_snap(sc, lids: list[str]) -> None:
    """The seed's fx (Fx_* fxmesh bins, particle emitters) were placed on the relief's depth; a T2 body sits at other
    depths, so each is re-derived from the seed and slid along its rest camera ray onto the T2 body's rest surface
    (the prefab frame's origin is the camera, so the slide is a scale of local coordinates: the rest frame is
    unchanged). Water vertices over no body take the slide of their nearest covered vertex (screen space); a
    particle's scale follows its slide so its rest size is kept. Writes stage_report buildings[lid]["fxSnap"]."""
    import shutil
    from scipy.spatial import cKDTree
    seed_stage = SEED / "unity_project" / S.ASSET_ROOT
    seed_rows = json.loads((seed_stage / "rows.json").read_text(encoding="utf-8"))
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    rp = S.WORK / "stage_report.json"
    rep_all = json.loads(rp.read_text(encoding="utf-8"))
    to_world = lambda v: sc.cpos + (np.asarray(v, np.float64) / sc.scale) @ sc.C.T
    for lid in lids:
        pk = S.PREFIX + lid
        fxb = [b for b in seed_rows[pk]["bins"] if b["name"].startswith("Fx_")]
        parts = seed_rows[pk].get("particles", [])
        if not fxb and not parts:
            continue
        Ps, Fs = [], []
        for b in rows[pk]["bins"]:
            if b["name"].startswith("Mesh_Body"):
                v, _, _, subs = S.read_bin(S.STAGE / pk / f"{b['name']}.bytes")
                Fs.append(np.concatenate(subs).reshape(-1, 3) + sum(len(x) for x in Ps))
                Ps.append(to_world(v))
        zb, _ = TP.zbuffer(sc.cam, np.concatenate(Ps), np.concatenate(Fs))
        zmin = cv2.erode(np.where(np.isfinite(zb), zb, 1e9).astype(np.float32), np.ones((5, 5), np.uint8))
        rep = {"bins": [], "particles": []}

        def body_z(wp):
            px, py, z = T.project(sc.cam, wp)
            xi = np.clip((px * SUPER).astype(int), 0, zb.shape[1] - 1)
            yi = np.clip((py * SUPER).astype(int), 0, zb.shape[0] - 1)
            zbv = zmin[yi, xi].astype(np.float64)
            return px, py, z, np.where(zbv < 1e8, zbv, np.nan)

        new_bins = [b for b in rows[pk]["bins"] if not b["name"].startswith("Fx_")]
        for b in fxb:
            for key in ("mesh", "uv2"):
                if b.get(key):
                    rel = Path(b[key]).relative_to(S.ASSET_ROOT)
                    shutil.copyfile(seed_stage / rel, S.STAGE / rel)
            for tex in (seed_stage / pk).glob(f"{b['name']}_*.png"):
                shutil.copyfile(tex, S.STAGE / pk / tex.name)
            if b.get("kind") == "fxmesh" and b.get("pos", [0, 0, 0]) == [0.0, 0.0, 0.0]:
                mp = S.STAGE / Path(b["mesh"]).relative_to(S.ASSET_ROOT)
                v, n, uv, subs = S.read_bin(mp)
                px, py, z, zbv = body_z(to_world(v))
                cov = np.isfinite(zbv)
                ratio = np.ones(len(v))
                if cov.any():
                    ratio[cov] = zbv[cov] * (1 - FX_WATER_EPS) / z[cov]
                    if (~cov).any():
                        _, j = cKDTree(np.stack([px[cov], py[cov]], 1)).query(np.stack([px[~cov], py[~cov]], 1))
                        ratio[~cov] = ratio[cov][j]
                S.write_bin(mp, np.asarray(v, np.float64) * ratio[:, None], n, uv, subs)
                rep["bins"].append({"name": b["name"], "coveredShare": round(float(cov.mean()), 3),
                                    "slideMedian": round(float(np.median(ratio)), 4),
                                    "slideRange": [round(float(ratio.min()), 4), round(float(ratio.max()), 4)]})
            new_bins.append(b)
        rows[pk]["bins"] = new_bins
        new_parts = []
        for q in parts:
            q = json.loads(json.dumps(q))
            px, py, z, zbv = body_z(to_world([q["pos"]]))
            r = 1.0 if not np.isfinite(zbv[0]) else float(zbv[0] * (1 - FX_PARTICLE_EPS) / z[0])
            q["pos"] = [float(x) * r for x in q["pos"]]
            q["scale"] = float(q["scale"]) * r
            new_parts.append(q)
            rep["particles"].append({"name": q["name"], "slide": round(r, 4), "overBody": bool(np.isfinite(zbv[0]))})
        rows[pk]["particles"] = new_parts
        rep_all["buildings"][lid]["fxSnap"] = rep
        print(lid, json.dumps(rep), flush=True)
    S.ROWS.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    rp.write_text(json.dumps(rep_all, indent=1), encoding="utf-8")


OCCLUDED_MAX = 0.01          # share of the body's rest px the staged terrain may hide after depth_slide


def depth_slide(sc, lid: str, P: np.ndarray, f: np.ndarray, zf: np.ndarray) -> tuple[np.ndarray, dict]:
    """Scale the fitted body about the rest camera's centre: its rest projection (the fit) is unchanged, only its depth
    moves. s = min(the seed relief's median camera z / the body's, the largest s that leaves at most OCCLUDED_MAX of the
    body's rest px behind the staged terrain, 1). The fit's contact pixel sits on the frame depth, which on a hill top
    is the far slope: tbrmcas3 had landed at median z 352 against the seed relief's 198, 55 m tall, 37% of it inside
    the hill (the rest frame showed terrain through the castle). Never pushed back (s <= 1)."""
    _, _, z = T.project(sc.cam, P)
    d = SEED / "unity_project" / S.ASSET_ROOT / (S.PREFIX + lid)
    v0 = S.read_bin(d / f"Mesh_Body_{lid}.bytes")[0]
    _, _, z0 = T.project(sc.cam, sc.cpos + (v0.astype(np.float64) / sc.scale) @ sc.C.T)
    s_seed = float(np.median(z0) / np.median(z))
    zb, _ = TP.zbuffer(sc.cam, P, f)
    cov = np.isfinite(zb)
    zfs = cv2.resize(zf.astype(np.float32), (W * SUPER, H * SUPER), interpolation=cv2.INTER_NEAREST)
    r = zfs[cov] / zb[cov]
    s_occ = float(np.quantile(r, OCCLUDED_MAX))
    s = min(1.0, s_seed, s_occ)
    c = np.asarray(sc.cam["pos"], np.float64)
    return c + (P - c) * s, {"scale": round(s, 4), "seedRatio": round(s_seed, 4), "occlusionBound": round(s_occ, 4),
                             "occludedBefore": round(float((r < 1).mean()), 4),
                             "occludedAfter": round(float((r < s).mean()), 4)}


LEAN_STEPS = np.linspace(0.0, 1.0, 11)
LEAN_HEADROOM = 1.05         # target irradiance = the painting's own linear max channel x this


def lean_normals(sc, lid: str, g: dict, P: np.ndarray, n: np.ndarray, idb: np.ndarray, fside: np.ndarray
                 ) -> tuple[np.ndarray, dict]:
    """The rig's ambient is nearly black off the key and fill (ambEq 0.012), and T2 surfaces the rest camera sees
    often face away from both (canopy cards, cliff flanks, castle side walls: median irradiance 0.008-0.08 on the
    visible side of tbrmcas3 / tbrmdw_4_2), so the de-lit painting clipped at albedo 1 and the rest frame went black
    there. Each vertex of a rest-visible face whose visible side is lit below the painting at its rest px is leaned
    toward the camera (the lane's relief normals lean toward up + viewer for the same reason) by the smallest step
    that lets the painting be reproduced (albedo <= 1). The bin carries these normals, so bake and game shade alike;
    faces hidden at rest keep Meshy's normals."""
    import conflux_full3d_env as E
    L = SC.layers()[lid]
    vis_f = np.unique(idb[idb >= 0])
    vote = np.zeros(len(P))
    for c in range(3):
        np.add.at(vote, g["f"][vis_f, c], fside[vis_f])
    vv = np.zeros(len(P), bool)
    vv[g["f"][vis_f].ravel()] = True
    idx = np.nonzero(vv)[0]
    px, py, _ = T.project(sc.cam, P[idx])
    import stronghold_full3d_buildings as BL
    big = G.SC_srgb_to_lin(TP.sprite_fill(L, 1.0, BL.native_mask(L)))
    sx, sy = px - L["x"] * SC.SCALE, py - L["y"] * SC.SCALE
    need = TP.sample(big, sx, sy).max(1) * LEAN_HEADROOM
    inside = (px < TW) & (py < TH)
    to_cam = sc.cam["pos"] - P[idx]
    to_cam /= np.linalg.norm(to_cam, axis=1, keepdims=True) + 1e-12
    # the side drawn at rest: the majority of the vertex's rest-visible faces (drawn_side)
    sgn = np.where(vote[idx] < 0, -1.0, 1.0)[:, None]
    m = n[idx] * sgn
    best = m.copy()
    done = ~inside
    for t in LEAN_STEPS:
        cand = m * (1 - t) + to_cam * t
        cand /= np.linalg.norm(cand, axis=1, keepdims=True) + 1e-12
        ok = ~done & (E.light(cand.astype(np.float32), sc.rig, sc.sun).max(-1) >= need)
        best[ok] = cand[ok]
        done |= ok
    best[~done] = to_cam[~done]
    out = n.copy()
    out[idx] = best * sgn
    moved = (np.abs((best * sgn - n[idx])).sum(1) > 1e-6)
    return out, {"visibleVerts": int(len(idx)), "leaned": int(moved.sum()),
                 "leanedShare": round(float(moved.mean()), 4) if len(idx) else 0.0}


SEED = SC.DATA / "candidates" / CFG["seed"]   # the installed candidate (read only)
RESID_MIN_PX = 1                            # frame px: smaller uncovered sprite components are not re-covered


def residual(sc, lid: str, zb: np.ndarray) -> dict:
    """Sprite px (the lane's fringe-dropped alpha, inside the painted rect) the Meshy body leaves uncovered at rest
    (painted ground skirts, foliage around a rock, pieces the model lacks) keep the seed's own front triangles there
    as Mesh_BodyRest_<layer>, with the seed's texture, so no px of the painting disappears at rest."""
    L = SC.layers()[lid]
    tgt = target_mask(L) > 127
    cover = cv2.resize(np.isfinite(zb).astype(np.uint8), (W, H), interpolation=cv2.INTER_AREA) > 0
    resid = tgt & ~cover
    n_, lab, st, _ = cv2.connectedComponentsWithStats(resid.astype(np.uint8), connectivity=8)
    keep = np.zeros(n_, bool)
    keep[1:] = st[1:, cv2.CC_STAT_AREA] >= RESID_MIN_PX
    resid = keep[lab]
    rep = {"spritePx": int(tgt.sum()), "residualPx": int(resid.sum()), "residualTris": 0}
    if not resid.any():
        return rep
    d = SEED / "unity_project" / S.ASSET_ROOT / (S.PREFIX + lid)
    v, nn, uv0, subs = S.read_bin(d / f"Mesh_Body_{lid}.bytes")
    P0 = sc.cpos + (v.astype(np.float64) / sc.scale) @ sc.C.T
    n0 = nn.astype(np.float64) @ sc.C.T
    rep["residualTris"] = TP.seed_residual(sc, S.PREFIX + lid, f"Mesh_BodyRest_{lid}", resid, P0, n0, uv0,
                                           np.concatenate(subs), d / f"Mesh_Body_{lid}_albedo.png", preview=False)
    return rep



def stage_layer(sc, lid: str, fr: dict, zf: np.ndarray) -> dict:
    """One fitted layer staged into sc (Mesh_Body_ / Mesh_BodyM_ / Mesh_BodyRest_ bins under S.STAGE); returns the
    layer's stage-report row. The caller drops the layer's old BodyRest / BodyM rows first."""
    g = load_layer_mesh(lid, SC.ROOT / fr["source"])
    P, n = world_mesh(g, fr)
    f, wrep = outward_faces(P, n, g["f"])
    P, drep = depth_slide(sc, lid, P, f, zf)
    # the painting's frame: a sprite cut by the frame edge (dw_2's tower, the pond's rim) is not the painting's
    # building past it, and the lane's framing gate wants every building inside the visible region at rest:
    # triangles with a corner outside the painted rect at rest are dropped (the relief lane stops there too)
    px_, py_, _ = T.project(sc.cam, P)
    outr = (px_ < 0) | (px_ >= TW) | (py_ < 0) | (py_ >= TH)
    keep = ~outr[f].any(1)
    g = {**g, "f": g["f"][keep]}
    f = f[keep]
    drep["clipRectDroppedTris"] = int((~keep).sum())
    tune = FIT_TUNE.get(lid, {})
    cut = tune.get("cutOvershootPx") or tune.get("cutOutsidePx")
    if cut:
        keep = ~overshoot_faces(sc, lid, P, f, cut, seen_only="cutOutsidePx" not in tune)
        g = {**g, "f": g["f"][keep]}
        f = f[keep]
        drep["overshootFacesCut"] = int((~keep).sum())
    P, n, uv_s, f, srep = TP.subdivide_screen(sc.cam, P, n, g["uv"], f, max_px=SUBDIV_PX)
    g = {**g, "uv": uv_s, "f": f}
    drep["subdivide"] = srep
    zb, idb = TP.zbuffer(sc.cam, P, f)
    fside = TP.drawn_side(sc.cam, P, f)
    n, lrep = lean_normals(sc, lid, g, P, n, idb, fside)
    brep = stage_split(sc, lid, g, P, n, f, zb, idb)
    brep["lean"] = lrep
    rrep = residual(sc, lid, zb)
    return {
        "kind": "meshy_t2", "method": "meshy_t2 (rampart_t2_buildings)", "source": fr["source"],
        "fit": {k: fr[k] for k in ("yaw", "scale", "iou", "precision", "recall", "fbeta", "stretchY",
                                   "contactPx", "worldHeight")},
        "tris": int(len(f)), "frontTris": brep["frontTris"], "sideQuads": 0, "texSize": brep["paintTex"],
        "texelsPerPx": float(SUPER), "bake": brep, "winding": wrep, "depth": drep, "twoSided": True, "residual": rrep}


# ------------------------------------------------------------------------------------------------ cli
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fit", "stage", "preview", "revert", "fx", "finish"])
    ap.add_argument("--state", default="max", choices=sorted(STATES))
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    only = [x for x in a.only.split(",") if x] or sorted(MESH_SOURCE)
    if a.cmd == "finish":
        return finish(S.Scene())
    if a.cmd == "fx":
        fx_snap(S.Scene(), [l for l in only if l not in BROKEN])
        return 0
    if a.cmd == "revert":
        revert_to_seed(sorted(BROKEN))
        print("kept seed:", sorted(BROKEN))
        return 0
    if a.cmd == "stage" and not a.only:
        only = [l for l in only if l not in BROKEN]
    if a.cmd == "preview":
        print(json.dumps(preview(a.state, WORK / "preview"), indent=1))
        return 0
    sc = S.Scene()
    WORK.mkdir(parents=True, exist_ok=True)
    zp = WORK / "frame_z.npy"
    if not zp.is_file():
        np.save(zp, frame_z(sc))
    zf = np.load(zp)
    fdir = WORK / "fits"
    fdir.mkdir(exist_ok=True)
    fits = {}
    for lid in only:
        fp = fdir / f"{lid}.json"
        src = str((MESHY / MESH_SOURCE[lid] / "model.glb").relative_to(SC.ROOT)).replace("\\", "/")
        if fp.is_file():
            fits[lid] = json.loads(fp.read_text(encoding="utf-8"))
        if a.cmd == "fit" or lid not in fits or fits[lid]["source"] != src or _fit_tune(fits[lid].get("tune")) != _fit_tune(FIT_TUNE.get(lid)):
            fits[lid] = fit_layer(sc, lid, zf)
            fits[lid]["tune"] = FIT_TUNE.get(lid)
            fp.write_text(json.dumps(fits[lid], indent=1), encoding="utf-8")
            r = fits[lid]
            print(lid, json.dumps({k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()
                                   if k in ("yaw", "scale", "iou", "precision", "recall", "worldHeight")}), flush=True)
    if a.cmd == "fit":
        return 0
    rp = S.WORK / "stage_report.json"
    rep_all = json.loads(rp.read_text(encoding="utf-8"))
    for lid in only:
        pk = S.PREFIX + lid
        rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
        rows[pk]["bins"] = [b for b in rows[pk]["bins"] if not b["name"].startswith(("Mesh_BodyRest_", "Mesh_BodyM_"))]
        S.ROWS.write_text(json.dumps(rows, indent=1), encoding="utf-8")
        rep_all.setdefault("buildings", {})[lid] = stage_layer(sc, lid, fits[lid], zf)
        print(lid, json.dumps(rep_all["buildings"][lid])[:400], flush=True)
    rp.write_text(json.dumps(rep_all, indent=1), encoding="utf-8")
    S.save_rows(sc)
    return 0


# ------------------------------------------------------------------------------------------------ preview


def preview(state: str, out: Path) -> dict:
    """The lane's offline preview (stronghold_full3d_preview shading) of the staged environment + one build state,
    at the rest pose and the vanilla camera's proof poses, with back-face culling on the Mesh_Body* pieces as the game
    draws them (the lane preview draws everything double-sided, which z-fights a two-sided body's two copies)."""
    import moderngl
    import stronghold_full3d_preview as PV
    sc = S.Scene()
    keep = {S.ENV_KEY} | {S.PREFIX + l for l in STATES[state]}
    S.load_staged_preview(sc, keep)
    R = PV.Renderer(sc.rig, sc.sun, W, H)
    for name, P, n, uv, tris, img, unlit in sc.preview:
        R.add(name, P, n, uv, tris, img, unlit=unlit)
    # PV.view's rows (right, up, -fwd) have determinant -1: the preview mirrors handedness, so the lane's outward
    # (np.cross) winding - Unity's clockwise front - is clockwise on the GL screen too
    R.ctx.front_face = "cw"
    cams = {"default": sc.cam, **S.pan_cams(sc)}
    shots = {}
    for key, cam in cams.items():
        mvp = PV.perspective(cam["fov"], W / H, 2.0, T.DOME_R * 1.2) @ PV.view(cam["pos"], cam["fwd"], cam["up"],
                                                                              cam["right"])
        R.fbo.use()
        R.ctx.clear(1.0, 0.0, 1.0, 1.0)
        p = R.prog
        p["mvp"].write(mvp.T.astype(np.float32).tobytes())
        for k in ("sunColor", "ambSky", "ambEq", "ambGround"):
            p[k].value = tuple(float(x) for x in R.rig[k])
        p["sunDir"].value = tuple(float(x) for x in R.sun)
        p["fillDir"].value = tuple(float(x) for x in R.rig.get("fillDir", (0, -1, 0)))
        p["fillColor"].value = tuple(float(x) for x in R.rig.get("fillColor", (0, 0, 0)))
        for pc in sorted(R.pieces, key=lambda q: not q["unlit"]):
            p["unlit"].value = int(pc["unlit"])
            p["cutout"].value = float(pc["cutout"])
            (R.ctx.disable if pc["unlit"] else R.ctx.enable)(moderngl.DEPTH_TEST)
            (R.ctx.enable if "/Mesh_Body_" in pc["name"] else R.ctx.disable)(moderngl.CULL_FACE)
            pc["tex"].use(0)
            p["tex"].value = 0
            pc["vao"].render()
        R.ctx.disable(moderngl.CULL_FACE)
        R.ctx.copy_framebuffer(R.out, R.fbo)
        a = np.frombuffer(R.out.read(components=3), np.uint8).reshape(H, W, 3)[::-1]
        out.mkdir(parents=True, exist_ok=True)
        Image.fromarray(a).save(out / f"{state}_{key}.png")
        shots[key] = str(out / f"{state}_{key}.png")
    return shots


def _unity_uv(uv: np.ndarray) -> np.ndarray:
    """trimesh already flips glTF v on import (v = 1 at the image's top row), which is the lane's convention (the
    terrain bins' v = 1 is the PNG's top row), so the uv passes through unchanged."""
    return np.asarray(uv, np.float32).copy()


if __name__ == "__main__":
    raise SystemExit(main())
