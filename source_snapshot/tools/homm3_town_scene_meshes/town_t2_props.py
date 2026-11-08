#!/usr/bin/env python3
"""Full-3D T2 towns, props pass (2026-09-30): place Meshy props (town_t2_props_gen.py) over the surfaces that streak at
the vanilla camera's reachable poses, and stage them into the environment prefab.

    TOWN_FULL3D_FACTION=<town> TOWN_FULL3D_CANDIDATE=<cand> python town_t2_props.py place [--max N]
    TOWN_FULL3D_FACTION=<town> TOWN_FULL3D_CANDIDATE=<cand> python town_t2_props.py stage
    TOWN_FULL3D_FACTION=<town> TOWN_FULL3D_CANDIDATE=<cand> python town_t2_props.py check

place  Targets per pose (conflux_town_camera_pan.proof_poses: sweep_left/right/high, cursor_left/right): the px
       town_t2_streak_map flags as streaks on the environment's own surfaces (terrain, outer hills, near terrain; never
       a building body or the modelled houses) plus the profile-free TARGET_RECTS below (screen regions measured on the
       editor renders that the texel metric misses: sky voids, texture-baked smears). Candidates: a prop type, a
       yaw, a scale jitter and a base on ground-like terrain (|n.y| > GROUND_NY) seen at a pose near a target px.
       Bases on painted water are refused (the prop would stand in the lake / river), as are bases inside another
       prop's footprint. Greedy: each round scores CANDS candidates by the target px they newly cover over all
       poses (projected hull in front of the scene), minus BUILDING_PEN per building px they cover, ENV_PEN per
       other environment px and REST_PEN per px of their hull seen at rest over the painted rect; a candidate seen
       there over more than REST_SEEN_MAX px is refused. Measured 2026-09-30 (castle): the streaking surfaces in the
       house clusters are the carved terrain 1.5 m (median) behind the houses' fronts, so a prop that covers them
       at a sweep is partly seen at rest; a strict hidden-at-rest rule placed nothing there. The rest frame's
       deviation is therefore bounded and paid for, not zero; check reports it exactly. Stops at --max instances or when no candidate gains
       MIN_GAIN px. Writes work/props/placement.json + per-pose overlays.
stage  One lit bin per prop type in the environment prefab (Mesh_Prop_<type>: every instance of that model),
       texture = the Meshy base colour gain-matched per channel (linear medians) so that the prop lit by the Hex/Lit
       rig matches the painting's own colours in the crop it was drawn from (clamped GAIN_CLAMP). Rewrites the
       catalog (stronghold_full3d_scene.write_catalog) and merges back the lane keys write_catalog does not own,
       plus a "props" block (types, instances, credits). stage_report["props"] records the same.
check  Exact moderngl rasterisation (town_full3d_t2_paint.zbuffer) of the full state + props at rest: prop px seen
       inside the painted rect. Fails (exit 1) when any instance shows more than REST_VISIBLE_MAX px.
       Grounded: at rest and at every pose, each instance's foot points (FOOT_SHARE) are projected and the scene
       (without props) is read BELOW_PX px under each; sky / nothing, or a surface more than DROP_RATIO deeper than
       the foot, means the foot overhangs a drop. An instance whose foot overhangs at more than FLOAT_MAX share at any
       view floats (measured 2026-09-30 on the dungeon and necropolis renders: props placed for the TARGET_RECTS sky
       voids stood on far ledges and read as rocks hanging in the air) and fails the check too.
       Seen from above: the overhang test alone misses those (the floor under them is there in the raster: the
       dungeon cave ceiling and the necropolis sky above the cliff are calibrated as floor and textured as wall /
       sky), so no view may look up at a base by more than -ELEV_MIN degrees: ground the camera looks up at is
       ground it barely sees, and a prop on it hangs in the air. Threshold from the 2026-09-30 editor renders: every
       instance that read as floating (dungeon cave-ceiling cluster, necropolis ruins in the sky) is at -4.2 deg or
       lower; the props that read as standing (necropolis mound 1.0, dungeon slime-side mushrooms -1.2..-0.2, tower
       crags) are above. A strict "seen from above" rule (+3 deg) dropped every necropolis prop, including those
       that stand. place applies the same rule to candidates.
       check first fails closed unless the staged Mesh_Prop_* bins and the catalog props block are placement.json's
       instances (staged_agrees: re-run stage after any drop / replace), and check.json records placementSha.
       drop-bad removes every failing instance (recorded in placement.json "dropped" with the reason); it refuses a
       check.json whose placementSha is not the current placement's (stale ids).
keep   `keep --ids 2,3 --why "..."`: an instance judged by eye to stand although the floating rule flags it carries
       that judgement (instance "keepReason"); check reports it under "kept" instead of failing on it. Only for the
       floating rule, never for rest visibility.
restore-exempt  move dropped instances named in FLOAT_EXEMPT_APPROVED (town, prop, pinned base) back into the
       placement; check then reports them under "exempt" when the elevation term alone flags them at the pinned
       minElevationDeg (any overhanging view still fails). Coordinator-approved entries only.
replace `replace --ids 2,3 --why "..."`: re-place flagged instances instead of dropping them (same index and type;
       the other instances stay fixed): place's score and base pool (ELEV_MIN applied), and only candidates whose
       foot passes the grounded rule; fails closed, leaving the placement unchanged, when an id has no candidate
       gaining MIN_GAIN. The old instance is kept in placement.json "replaced". Re-run stage and check afterwards.
drop   `drop --ids 2,3 --why "..."`: an instance judged by eye to float although the rule passes it (recorded in
       "dropped" with "by eye: <why>"; 2026-09-30: the rampart oaks, foliage hanging against the white void).
Proof tier: generated artifact (offline raster). Whether the streaks read as fixed is judged on the editor renders.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stronghold_full3d_common as SC  # noqa: E402
import stronghold_full3d_scene as S  # noqa: E402
import stronghold_full3d_terrain as T  # noqa: E402
import stronghold_full3d_ground as G  # noqa: E402
import town_full3d_t2_paint as TP  # noqa: E402
import town_t2_streak_map as SM  # noqa: E402
import town_t2_props_gen as GEN  # noqa: E402

W, H = SC.W, SC.H
POSES = {"sweep_left": 1.0, "sweep_right": 1.0, "sweep_high": 1.0, "cursor_left": 0.5, "cursor_right": 0.5}
DS = 2                      # scoring raster = frame / DS
GROUND_NY = 0.7
CANDS = 20000
MIN_GAIN = 150.0            # frame px (scored at 1/DS^2 and scaled back)
BUILDING_PEN = 2.0
ENV_PEN = 0.12
SCALE_JITTER = (0.8, 1.25)
REST_EPS = 0.004
REST_SEEN_MAX = 600         # frame px of a candidate's rest hull allowed over the painted rect (penalised below)
REST_OUT_MAX = 25000        # frame px of a candidate seen at rest outside the painted rect (the extension)
NEAR_MIN = 8.0              # every prop vertex at least this far in front of the rest camera
REST_PEN = 0.75             # per such px: a prop drawn over the painting at rest must buy it back in streak px
REST_VISIBLE_MAX = 600      # exact check: frame px of one instance visible inside the painted rect at rest
FOOT_SHARE = 0.03           # grounded check: model vertices in the lowest 3% of its height are its foot
BELOW_PX = 4                # ... sampled this many frame px below each projected foot point
DROP_RATIO = 1.15           # ... the surface there is a drop-off when its depth exceeds the foot's by this factor
FLOAT_MAX = 0.5             # ... an instance floats at a view when more than this share of its foot overhangs one
ELEV_MIN = -4.0             # deg: no camera (rest + POSES) may look UP at a prop's base by more than this much
GAIN_CLAMP = (0.2, 2.0)
# replace --dropped (coordinator 2026-10-02, Stronghold: 18 of 18 props dropped on the restaged terrain, "re-placed, not
# dropped"): a wider search than place's (more base samples per pose, a wider ring around the targets, more
# candidates) and every candidate's base snapped down onto the staged ground (town_full3d_ground_contact.Ground, the
# GPU lookup) under its own foot, so the foot meets the ground instead of overhanging the slope it was sampled on.
WIDE_POOL_PER_POSE = 12000  # place: 4000
WIDE_TARGET_RING = 121      # px (place: 61)
WIDE_CANDS = 60000          # place: CANDS
SNAP_SINK_MAX = 0.15        # snap: the foot's ground may span at most this share of the prop's height (the uphill
                            # side of the foot is that much in the ground); a steeper footing is refused
# Rock formations (coordinator 2026-10-02, follow-up to Stronghold's 18/18 dropped props): a natural rock may sit with
# its uphill side buried in the slope, which is physically right and not a floating error. Only the props named here,
# and only with replace --dropped --rock-embed, use ROCK_EMBED_MAX instead of SNAP_SINK_MAX: the snap still rests the
# lowest foot point on the lowest ground under the foot (the downhill side touches, nothing floats), and the uphill
# side may be buried up to ROCK_EMBED_MAX of the height. The visible part stays under check and the recipe's gates.
# Never built structures.
ROCK_FORMATIONS = {("stronghold", "spire"), ("stronghold", "butte"), ("stronghold", "cones"), ("cove", "crag"),
                   ("factory", "mesa"), ("bulwark", "boulder")}
ROCK_EMBED_MAX = 0.5
# Scoped floating-rule exemptions (coordinator 2026-10-02, finish lane): one named instance per entry, keyed by
# (town, prop) and pinned to its placement base (m) and its measured minElevationDeg. Only the ELEV_MIN term is
# exempted (the foot-overhang share must still pass FLOAT_MAX), only for an instance at the pinned base, and only
# while its elevation is the pinned value: a moved or re-measured instance fails the check again. Stronghold's
# butte was dropped from sh_carve_v1 by the elevation term alone; without it the ridge it hides shows painted-sky
# patches and a smear at sweep_right / sweep_high / loop_096 / orbit_y-18 that the installed pb_v1 covers with it.
# restore-exempt brings such a dropped instance back. A new entry is a new decision (validator pin).
FLOAT_EXEMPT_APPROVED = {
    ("stronghold", "butte"): {"base": (154.4405, 31.3531, 152.9652), "minElevationDeg": -8.39,
                              "reason": "ridge-top butte hiding the far ridge's painted-sky patches (pb_v1 has it); "
                                        "dropped by the elevation term only"},
}
FLOAT_EXEMPT_BASE_TOL = 0.01    # m
FLOAT_EXEMPT_ELEV_TOL = 0.01    # deg


def float_exempt(town: str, inst: dict) -> dict | None:
    """The approved exemption entry for this placed instance, or None (wrong town / prop, or not at the pinned base)."""
    ex = FLOAT_EXEMPT_APPROVED.get((town, inst["prop"]))
    if ex is None:
        return None
    if np.abs(np.asarray(inst["base"], np.float64) - np.asarray(ex["base"], np.float64)).max() > FLOAT_EXEMPT_BASE_TOL:
        return None
    return ex
SNAP_CHUNK_PTS = 40000      # snap.batch: foot points per Ground.gap call (its point x cell-triangle pairs under the cap)
GAIN_PX_SHARE = 0.35
GAIN_CHROMA = 0.15
PROPS_DIR = S.WORK / "props"
# Screen regions (frame px at that pose) the texel metric misses, measured on the t2 editor renders (2026-09-30).
TARGET_RECTS: dict = {
    "rampart": {"sweep_left": [[0, 0, 170, 150], [0, 60, 60, 520]], "sweep_right": [[0, 150, 220, 330]]},
    "tower": {"sweep_left": [[0, 560, 1920, 1080]], "sweep_right": [[0, 600, 1920, 1080], [1500, 0, 1920, 560]],
              "sweep_high": [[0, 560, 1920, 1080]]},
    "dungeon": {"sweep_right": [[1400, 0, 1920, 300]], "sweep_high": [[1400, 0, 1920, 300]]},
    "necropolis": {"sweep_right": [[1700, 0, 1920, 400]], "sweep_high": [[1700, 0, 1920, 400]]},
}


# ------------------------------------------------------------------------------------------------ models
def load_prop(path: Path) -> dict:
    """GLB -> painting-world convention (x negated as glTFast imports, winding restored), base at y 0, footprint
    centred on x = z = 0, height 1."""
    import trimesh
    m = trimesh.load(str(path), force="mesh", process=False)
    V = np.asarray(m.vertices, np.float64).copy()
    V[:, 0] *= -1.0
    F = np.asarray(m.faces, np.int64)[:, [0, 2, 1]]
    uv = np.asarray(m.visual.uv, np.float64)
    N = np.asarray(m.vertex_normals, np.float64).copy()
    N[:, 0] *= -1.0
    V[:, 1] -= V[:, 1].min()
    low = V[V[:, 1] <= np.percentile(V[:, 1], 8)]
    V[:, 0] -= np.median(low[:, 0])
    V[:, 2] -= np.median(low[:, 2])
    h = float(V[:, 1].max())
    V /= h
    tex = np.asarray(m.visual.material.baseColorTexture.convert("RGB"))
    foot = float(np.percentile(np.hypot(V[:, 0], V[:, 2]), 90))
    rng = np.random.default_rng(0)
    samp = rng.choice(len(V), min(len(V), 600), replace=False)
    return {"V": V, "F": F, "uv": uv, "N": N, "tex": tex, "foot": foot, "samp": samp}


def rot_y(deg: float) -> np.ndarray:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def instance_world(model: dict, inst: dict, idx=None) -> np.ndarray:
    V = model["V"] if idx is None else model["V"][idx]
    return (V * inst["height"]) @ rot_y(inst["yaw"]).T + np.asarray(inst["base"])


def world_height(sc, spec: dict, zrest: np.ndarray) -> float:
    """World height of a prop type: its painted height (frame px) at the depth of its crop's foot under the rest
    camera (the median depth of the crop's bottom fifth, painted-rect px)."""
    x0, y0, x1, y1 = spec["rectFrame"]
    band = zrest[int(y1 - (y1 - y0) * 0.2):int(y1), int(x0):int(x1)]
    z = float(np.median(band[np.isfinite(band)]))
    mpp = 2 * z * math.tan(math.radians(sc.cam["fov"]) / 2) / H
    return spec["paintedPx"] * mpp


def prop_specs(town: str) -> dict:
    out = {}
    for prop in GEN.PROPS.get(town, {}):
        d = GEN.out_dir(town, prop)
        if (d / "model.glb").is_file() and not (d / "rejected.json").is_file():   # rejected.json: why not placed
            out[prop] = {**json.loads((d / "spec.json").read_text(encoding="utf-8")), "dir": str(d),
                         "glb": str(d / "model.glb")}
    return out


# ------------------------------------------------------------------------------------------------ scene
def scene_buffers(sc):
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    keys = [S.PREFIX + "environment"] + [S.PREFIX + l for l in SC.FP.STATES["full"]]
    P, UV, F, owner, names, texs = SM.load_bins(sc, rows, keys)
    env = np.array([n.startswith("environment/") and not n.startswith("environment/Mesh_Houses")
                    and not n.startswith("environment/Mesh_Prop_") for n in names])
    return P, UV, F, owner, names, texs, env


def pose_state(sc, cam, P, UV, F, owner, texs, env, town, pose):
    z, fid = TP.zbuffer(cam, P, F, sup=1)
    vis = fid >= 0
    faces = np.unique(fid[vis])
    s1, s2 = SM.face_stretch(cam, P, UV, F, owner, texs, faces)
    lut = np.zeros(len(F), bool)
    lut[faces[(s1 >= SM.S1_MIN) & (s1 / s2 >= SM.ANISO_MIN)]] = True
    ob = np.where(vis, owner[np.where(vis, fid, 0)], -1)
    is_env = vis & env[np.maximum(ob, 0)]
    streak = vis & lut[np.where(vis, fid, 0)] & is_env
    extra = np.zeros_like(streak)
    for r in TARGET_RECTS.get(town, {}).get(pose, []):
        extra[r[1]:r[3], r[0]:r[2]] = True
    target = streak | (extra & (is_env | ~vis))
    building = vis & ~is_env
    inside, wp = SM.rest_rect_mask(cam, z, sc)
    gx = np.zeros_like(wp)
    gy = np.zeros_like(wp)
    gx[:, 1:-1] = wp[:, 2:] - wp[:, :-2]
    gy[1:-1] = wp[2:] - wp[:-2]
    n = np.cross(gx, gy)
    ny = np.abs(n[..., 1]) / (np.linalg.norm(n, axis=-1) + 1e-9)
    ground = is_env & (ny > GROUND_NY) & np.isfinite(z)
    return {"z": z, "target": target, "streak": streak, "building": building, "env": is_env, "ground": ground,
            "wp": wp}


def pool(a: np.ndarray, how) -> np.ndarray:
    h, w = a.shape[0] // DS, a.shape[1] // DS
    return how(how(a[:h * DS, :w * DS].reshape(h, DS, w, DS), axis=3), axis=1)


def water_at_rest(sc, pts: np.ndarray, paint: np.ndarray) -> np.ndarray:
    px, py, _ = T.project(sc.cam, pts)
    ok = (px >= 0) & (px < SC.TW) & (py >= 0) & (py < SC.TH)
    out = np.zeros(len(pts), bool)
    c = paint[np.clip(py[ok], 0, SC.TH - 1).astype(int), np.clip(px[ok], 0, SC.TW - 1).astype(int)].astype(np.float32)
    out[ok] = (c[:, 2] > c[:, 0] + 18) & (c[:, 2] >= c[:, 1])
    return out


def hull(cam, pts: np.ndarray):
    px, py, zc = T.project(cam, pts)
    if (zc <= 1.0).any():
        return None
    q = np.stack([px / DS, py / DS], 1).astype(np.float32)
    hh = cv2.convexHull(q).astype(np.int32)
    x0, y0 = hh[:, 0, 0].min(), hh[:, 0, 1].min()
    x1, y1 = hh[:, 0, 0].max() + 1, hh[:, 0, 1].max() + 1
    w, h = W // DS, H // DS
    if x1 <= 0 or y1 <= 0 or x0 >= w or y0 >= h:
        return None
    X0, Y0, X1, Y1 = max(x0, 0), max(y0, 0), min(x1, w), min(y1, h)
    m = np.zeros((y1 - y0, x1 - x0), np.uint8)
    cv2.fillPoly(m, [hh - [x0, y0]], 1)
    m = m[Y0 - y0:Y1 - y0, X0 - x0:X1 - x0].astype(bool)
    return (X0, Y0, X1, Y1), m, float(zc.min()), float(np.median(zc))


# ------------------------------------------------------------------------------------------------ place
def place_context(pool_per_pose: int = 4000, ring: int = 61) -> dict:
    """Everything place scores a candidate against: the scene, the reachable poses' streak targets (pooled), the rest
    depth and the base pool (ground near a target, not on painted water, not looked up at (ELEV_MIN), hidden at rest
    or outside the painted rect). replace --dropped widens pool_per_pose / ring (WIDE_*)."""
    town = SC.FACTION
    specs = prop_specs(town)
    if not specs:
        raise SystemExit(f"place: no Meshy props for {town} (town_t2_props_gen.py mesh)")
    sc = S.Scene()
    P, UV, F, owner, names, texs, env = scene_buffers(sc)
    cams = S.pan_cams(sc)
    zrest, _ = TP.zbuffer(sc.cam, P, F, sup=1)
    paint = np.asarray(S.homm3_reference(SC.FP.STATES["full"]))
    models = {k: load_prop(Path(v["glb"])) for k, v in specs.items()}
    heights = {k: world_height(sc, v, zrest) for k, v in specs.items()}
    st = {p: pose_state(sc, cams[p], P, UV, F, owner, texs, env, town, p) for p in POSES}
    sm = {p: {"z": pool(np.where(np.isfinite(s["z"]), s["z"], 1e9), np.min), "target": pool(s["target"], np.max),
              "building": pool(s["building"], np.max), "env": pool(s["env"], np.max)} for p, s in st.items()}
    zr = pool(np.where(np.isfinite(zrest), zrest, 1e9), np.min)
    inside_r = np.zeros_like(zr, bool)
    inside_r[:SC.TH // DS, :SC.TW // DS] = True
    before = {p: int(sm[p]["target"].sum() * DS * DS) for p in POSES}
    # base pool: ground px near target px, per pose
    rng = np.random.default_rng(7)
    bases = []
    for p, s in st.items():
        tgt = cv2.dilate(s["target"].astype(np.uint8), np.ones((ring, ring), np.uint8)).astype(bool)
        ys, xs = np.nonzero(s["ground"] & tgt)
        if len(ys):
            k = rng.choice(len(ys), min(len(ys), pool_per_pose), replace=False)
            bases.append(s["wp"][ys[k], xs[k]])
    if not bases:
        raise SystemExit("place: no ground near any target")
    bases = np.concatenate(bases).astype(np.float64)
    bases = bases[~water_at_rest(sc, bases, paint)]
    views = {"rest": sc.cam, **{p: cams[p] for p in POSES}}
    bases = bases[np.array([elevation(views, b) >= ELEV_MIN for b in bases], bool)]
    # a base must itself be hidden at rest inside the painted rect (or lie outside it): a prop standing on ground the
    # rest camera sees would be drawn over the painting
    bx, by, bz = T.project(sc.cam, bases)
    ins = (bx >= 0) & (bx < SC.TW) & (by >= 0) & (by < SC.TH) & (bz > 1)
    zb = np.full(len(bases), np.inf)
    zb[ins] = zrest[np.clip(by[ins], 0, H - 1).astype(int), np.clip(bx[ins], 0, W - 1).astype(int)]
    bases = bases[~ins | (zb < bz * (1 + REST_EPS))]   # hidden, or the rest front itself (penalised in the score)
    print(f"base pool {len(bases)} ({int(ins.sum())} inside the rect before the rest-hidden filter)", flush=True)
    return {"town": town, "specs": specs, "sc": sc, "P": P, "F": F, "owner": owner, "names": names, "cams": cams,
            "models": models,
            "heights": heights, "st": st, "sm": sm, "zr": zr, "inside_r": inside_r, "before": before, "rng": rng,
            "bases": bases, "views": views}


def ground_snapper(ctx: dict, device: str | None = None, rock_embed: bool = False):
    """snap(mdl, inst) -> inst with its base moved down onto the staged ground under its foot (the lowest ground
    under the FOOT_SHARE points, so no foot point overhangs), or None (no ground under part of the foot, a footing
    spanning more than SNAP_SINK_MAX of the height, or a snapped base the cameras look up at past ELEV_MIN). The
    ground is the environment's terrain sheets (town_full3d_ground_contact.GROUND) in the Ground lookup on the GPU.
    The foot points are measured lifted by the instance height: Ground.gap only counts surfaces up to 0.5 m above a
    point, so an uphill foot point under the slope read as "no ground" (Stronghold 2026-10-02: 59,999 of 60,000
    cones candidates refused noGround); lifted, the highest ground within the prop's height is found, noGround means
    none there, and SNAP_SINK_MAX judges the slope."""
    import town_full3d_ground_contact as GC
    import town_gpu_kernels as GK
    env_ground = np.array([n.startswith("environment/") and bool(GC.GROUND.match(n.split("/", 1)[1]))
                           for n in ctx["names"]])
    Fg = ctx["F"][env_ground[ctx["owner"]]]
    if not len(Fg):
        raise SystemExit("replace: no environment terrain sheet to snap onto")
    ground = GC.Ground(np.asarray(ctx["P"], np.float64), Fg, GK.resolve_device(device))
    views = ctx["views"]

    def sink_max(prop: str) -> float:
        return ROCK_EMBED_MAX if rock_embed and (ctx["town"], prop) in ROCK_FORMATIONS else SNAP_SINK_MAX

    def foot_gaps(mdl, insts: list):
        """(fi, foot points per candidate, lifts, gaps of the lifted foot points: one ground lookup for all)."""
        fi = np.nonzero(mdl["V"][:, 1] <= FOOT_SHARE)[0]
        Qs = [instance_world(mdl, inst, fi) for inst in insts]
        # measured from the foot points lifted by the instance height: Ground.gap only sees surfaces up to 0.5 m
        # above a point, so a foot point buried in an uphill slope read as "no ground"; lifted, the gap finds the
        # highest ground within the prop's own height (noGround = none there), and steepFooting judges the slope
        lifts = [np.array([0.0, inst["height"], 0.0]) for inst in insts]
        Qa = np.concatenate([Q + l for Q, l in zip(Qs, lifts)]) if Qs else np.zeros((0, 3))
        # chunked under the VRAM cap (gap is pointwise: the chunking changes no bit)
        g_all = np.concatenate([ground.gap(Qa[i:i + SNAP_CHUNK_PTS]) for i in range(0, len(Qa), SNAP_CHUNK_PTS)]) \
            if len(Qa) else np.zeros(0)
        return fi, Qs, lifts, g_all

    def snap_batch(mdl, insts: list):
        """[snapped inst or None] for many candidates with one ground lookup (Ground.gap is pointwise, so the result
        equals snap() per candidate bit for bit), and the refusal counts by reason."""
        fi, Qs, lifts, g_all = foot_gaps(mdl, insts)
        out, why = [], {"noGround": 0, "steepFooting": 0, "elevation": 0}
        for i, (inst, Q) in enumerate(zip(insts, Qs)):
            g = g_all[i * len(fi):(i + 1) * len(fi)]
            if not np.isfinite(g).all():
                out.append(None)
                why["noGround"] += 1
                continue
            hg = Q[:, 1] + lifts[i][1] - g
            if float(hg.max() - hg.min()) > sink_max(inst["prop"]) * inst["height"]:
                out.append(None)
                why["steepFooting"] += 1
                continue
            b = list(inst["base"])
            b[1] = float(b[1] + (hg.min() - Q[:, 1].min()))
            if elevation(views, b) < ELEV_MIN:
                out.append(None)
                why["elevation"] += 1
                continue
            out.append({**inst, "base": b, "snapM": round(float(b[1] - inst["base"][1]), 3),
                        **({"embedShare": round(float(hg.max() - hg.min()) / inst["height"], 3),
                            "rockEmbed": ROCK_EMBED_MAX} if sink_max(inst["prop"]) != SNAP_SINK_MAX else {})})
        return out, why

    def snap(mdl, inst):
        return snap_batch(mdl, [inst])[0][0]
    snap.batch = snap_batch
    snap.foot_gaps = foot_gaps
    snap.device = ground.device
    return snap


def _draw(ctx: dict, prop) -> dict:
    """One random candidate (pick's draw order: type, yaw, height, base)."""
    rng = ctx["rng"]
    prop_ = prop if prop is not None else list(ctx["specs"])[rng.integers(len(ctx["specs"]))]
    return {"prop": prop_, "yaw": float(rng.uniform(0, 360)),
            "height": ctx["heights"][prop_] * float(rng.uniform(*SCALE_JITTER)),
            "base": ctx["bases"][rng.integers(len(ctx["bases"]))].tolist()}


def pick(ctx: dict, placed: list, prop=None, foot_ok=None, snap=None, cands: int = CANDS, batched: bool = False):
    """The best of cands candidates against the targets still uncovered: (gain, inst, perPose) or None. prop fixes
    the type (replace keeps an instance's own), foot_ok(mdl, inst) refuses a candidate (replace: the grounded rule),
    snap(mdl, inst) moves its base onto the ground first or refuses it (replace --dropped). batched (needs a fixed
    prop and snap): every candidate is drawn first (the same draws, in the same order) and snapped with one ground
    lookup (snap.batch: the GPU path; Ground.gap is pointwise, so the answer is the per-candidate loop's, bit for bit;
    replace --dropped --parity checks it). The refusal counts land in ctx["snapRefused"]."""
    models = ctx["models"]
    if batched:
        if prop is None or snap is None:
            raise SystemExit("pick: batched needs a fixed prop and a snap")
        drawn = [_draw(ctx, prop) for _ in range(cands)]
        snapped, why = snap.batch(models[prop], drawn)
        ctx["snapRefused"] = why
        todo = [x for x in snapped if x is not None]
    best = None
    for k in range(len(todo) if batched else cands):
        if batched:
            inst = todo[k]
        else:
            inst = _draw(ctx, prop)
            if snap is not None:
                inst = snap(models[inst["prop"]], inst)
                if inst is None:
                    continue
        r = _score(ctx, placed, inst)
        if r is None:
            continue
        gain, per = r
        if (best is None or gain > best[0]) and (foot_ok is None or foot_ok(models[inst["prop"]], inst)):
            best = (gain, inst, per)
    return best


def _score(ctx: dict, placed: list, inst: dict):
    """pick's score of one (snapped) candidate: (gain, perPose), or None when it is refused (spacing, near the rest
    camera, too much of it seen at rest)."""
    sc, cams, sm, zr, inside_r = ctx["sc"], ctx["cams"], ctx["sm"], ctx["zr"], ctx["inside_r"]
    models = ctx["models"]
    mdl = models[inst["prop"]]
    foot = mdl["foot"] * inst["height"]
    if any(np.hypot(inst["base"][0] - q["base"][0], inst["base"][2] - q["base"][2]) <
           0.8 * (foot + models[q["prop"]]["foot"] * q["height"]) for q in placed):
        return None
    pts = instance_world(mdl, inst, mdl["samp"])
    if (T.project(sc.cam, pts)[2] < NEAR_MIN).any():
        return None         # at / behind the rest camera: a giant prop in front of the whole frame
    hr = hull(sc.cam, pts)
    seen = seen_out = 0
    if hr is not None:
        (X0, Y0, X1, Y1), m, zmin, _ = hr
        front = m & (zr[Y0:Y1, X0:X1] > zmin * (1 + REST_EPS))
        seen = int((front & inside_r[Y0:Y1, X0:X1]).sum()) * DS * DS
        seen_out = int((front & ~inside_r[Y0:Y1, X0:X1]).sum()) * DS * DS
        if seen > REST_SEEN_MAX or seen_out > REST_OUT_MAX:
            return None
    gain, per = -REST_PEN * seen - ENV_PEN * seen_out, {"rest": {"seenInsideRect": seen, "seenOutside": seen_out}}
    for p, wgt in POSES.items():
        hp = hull(cams[p], pts)
        if hp is None:
            continue
        (X0, Y0, X1, Y1), m, _, zmed = hp
        front = m & (sm[p]["z"][Y0:Y1, X0:X1] > zmed)
        t = int((front & sm[p]["target"][Y0:Y1, X0:X1]).sum())
        b = int((front & sm[p]["building"][Y0:Y1, X0:X1]).sum())
        e = int((front & sm[p]["env"][Y0:Y1, X0:X1] & ~sm[p]["target"][Y0:Y1, X0:X1]).sum())
        gain += wgt * (t - BUILDING_PEN * b - ENV_PEN * e) * DS * DS
        per[p] = {"target": t * DS * DS, "building": b * DS * DS}
    return gain, per


def cover(ctx: dict, inst: dict) -> None:
    """Mark the targets an instance covers at each pose as covered (the greedy's state update)."""
    mdl = ctx["models"][inst["prop"]]
    pts = instance_world(mdl, inst, mdl["samp"])
    for p in POSES:
        hp = hull(ctx["cams"][p], pts)
        if hp is None:
            continue
        (X0, Y0, X1, Y1), m, _, zmed = hp
        sm = ctx["sm"][p]
        front = m & (sm["z"][Y0:Y1, X0:X1] > zmed)
        sm["target"][Y0:Y1, X0:X1] &= ~front
        sm["env"][Y0:Y1, X0:X1] &= ~front
        sm["z"][Y0:Y1, X0:X1] = np.where(front, zmed, sm["z"][Y0:Y1, X0:X1])


def overlays(ctx: dict, placed: list) -> None:
    cams = ctx["cams"]
    for p, s in ctx["st"].items():
        img = np.full((H, W, 3), 40, np.uint8)
        img[s["env"]] = [90, 90, 90]
        img[s["building"]] = [60, 60, 140]
        img[s["target"]] = [230, 40, 40]
        im = Image.fromarray(img)
        d = ImageDraw.Draw(im)
        for inst in placed:
            mdl = ctx["models"][inst["prop"]]
            px, py, zc = T.project(cams[p], instance_world(mdl, inst, mdl["samp"]))
            if (zc > 1).all():
                q = cv2.convexHull(np.stack([px, py], 1).astype(np.float32))[:, 0]
                d.polygon([tuple(map(float, v)) for v in q], outline=(255, 255, 0))
        im.save(PROPS_DIR / f"place_{p}.png")


def place(max_n: int) -> dict:
    ctx = place_context()
    specs, heights, sm = ctx["specs"], ctx["heights"], ctx["sm"]
    placed = []
    for it in range(max_n):
        best = pick(ctx, placed)
        if best is None or best[0] < MIN_GAIN:
            break
        gain, inst, per = best
        inst["gain"] = round(gain, 1)
        inst["perPose"] = per
        placed.append(inst)
        cover(ctx, inst)
        print(f"{it:2d} {inst['prop']:10s} gain {gain:8.0f} h {inst['height']:.2f} rest {per['rest']['seenInsideRect']} "
              + " ".join(f"{p}:{v['target']}" for p, v in per.items() if p != "rest"), flush=True)
    PROPS_DIR.mkdir(parents=True, exist_ok=True)
    after = {p: int(sm[p]["target"].sum() * DS * DS) for p in POSES}
    out = {"schema": "town_t2_props.v1", "faction": ctx["town"], "candidate": S.CANDIDATE,
           "types": {k: {"glb": v["glb"], "worldHeight": round(heights[k], 3), "rectFrame": v["rectFrame"],
                         "paintedPx": v["paintedPx"], "description": v["description"]} for k, v in specs.items()},
           "instances": placed, "targetPxBefore": ctx["before"], "targetPxAfterEstimate": after,
           "params": {"cands": CANDS, "minGain": MIN_GAIN, "buildingPen": BUILDING_PEN, "envPen": ENV_PEN,
                      "targetRects": TARGET_RECTS.get(ctx["town"], {})}}
    (PROPS_DIR / "placement.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    overlays(ctx, placed)
    print(json.dumps({"instances": len(placed), "before": ctx["before"], "afterEstimate": after}))
    return out


def grounded_rule(ctx: dict):
    """foot_ok(mdl, inst): check's grounded rule on the scene without props (no foot overhanging a drop at more than
    FLOAT_MAX share at rest or at any pose)."""
    sc = ctx["sc"]
    views = {"rest": sc.cam, **{q: c for q, c in S.pan_cams(sc).items() if q in POSES}}
    zs = {v: TP.zbuffer(c, ctx["P"], ctx["F"], sup=1)[0] for v, c in views.items()}

    def foot_ok(mdl, inst):
        foot = instance_world(mdl, inst, np.nonzero(mdl["V"][:, 1] <= FOOT_SHARE)[0])
        for v, cam in views.items():
            px, py, zc = T.project(cam, foot)
            ok = (zc > 1) & (px >= 0) & (px < W) & (py >= 0) & (py + BELOW_PX < H)
            if not ok.any():
                continue
            zb = zs[v][(py[ok] + BELOW_PX).astype(int), px[ok].astype(int)]
            if (~np.isfinite(zb) | (zb > zc[ok] * DROP_RATIO)).mean() > FLOAT_MAX:
                return False
        return True
    return foot_ok


PARITY_CANDS = 3000         # replace --dropped --parity: candidates the cpu loop and the cuda batch both score


def snap_parity(ctx: dict, placed: list, prop: str, foot_ok) -> dict:
    """The batched cuda snap against the per-candidate cpu reference on the same PARITY_CANDS draws: the snapped
    candidates (every base, bit for bit) and pick's answer must be equal; fails closed otherwise."""
    state = ctx["rng"].bit_generator.state
    ref_snap, gpu_snap = ground_snapper(ctx, "cpu"), ground_snapper(ctx, "cuda")
    mdl = ctx["models"][prop]
    drawn = [_draw(ctx, prop) for _ in range(PARITY_CANDS)]
    # the raw lifted-foot gaps first (meaningful even when every candidate is refused): cpu per candidate vs cuda batch
    g_ref = np.concatenate([ref_snap.foot_gaps(mdl, [x])[3] for x in drawn])
    g_gpu = gpu_snap.foot_gaps(mdl, drawn)[3]
    if g_ref.tobytes() != g_gpu.tobytes():
        raise SystemExit(f"replace --dropped --parity: the cuda foot gaps differ from the cpu reference on "
                         f"{int((g_ref != g_gpu).sum())} of {len(g_ref)} points")
    ref = [ref_snap(mdl, x) for x in drawn]
    gpu, why = gpu_snap.batch(mdl, drawn)
    if json.dumps(ref) != json.dumps(gpu):
        bad = sum(json.dumps(a) != json.dumps(b) for a, b in zip(ref, gpu))
        raise SystemExit(f"replace --dropped --parity: the cuda snap differs from the cpu reference on {bad} of "
                         f"{PARITY_CANDS} candidates")
    ctx["rng"].bit_generator.state = state
    a = pick(ctx, placed, prop=prop, foot_ok=foot_ok, snap=ref_snap, cands=PARITY_CANDS)
    ctx["rng"].bit_generator.state = state
    b = pick(ctx, placed, prop=prop, foot_ok=foot_ok, snap=gpu_snap, cands=PARITY_CANDS, batched=True)
    if json.dumps(a) != json.dumps(b):
        raise SystemExit("replace --dropped --parity: pick's answer differs between the cpu loop and the cuda batch")
    ctx["rng"].bit_generator.state = state
    return {"cands": PARITY_CANDS, "gapPoints": len(g_ref), "finiteGaps": int(np.isfinite(g_ref).sum()),
            "snapped": sum(x is not None for x in gpu), "refused": why,
            "best": None if a is None else round(a[0], 1)}


def replace_dropped(why: str, device: str | None = None, parity: bool = False, rock_embed: bool = False,
                    dry_run: bool = False) -> dict:
    """replace --dropped: re-place every dropped instance (same prop type and place's height rule) with the wide
    search (WIDE_*) and the ground snap (ground_snapper), refusing candidates that fail the grounded rule; the placed
    instances stay fixed and their cover is taken first. An instance with no candidate gaining MIN_GAIN stays
    dropped, recorded with "replaceTried" (coordinator 2026-10-02: ship what re-places cleanly). Re-run stage and
    check afterwards: check stays the acceptance (rest visibility, grounded, elevation)."""
    p = PROPS_DIR / "placement.json"
    pl = json.loads(p.read_text(encoding="utf-8"))
    todo = pl.get("dropped") or []
    if not todo:
        raise SystemExit("replace --dropped: nothing is dropped")
    ctx = place_context(WIDE_POOL_PER_POSE, WIDE_TARGET_RING)
    unknown = sorted({x["prop"] for x in todo} - set(ctx["models"]))
    if unknown:
        raise SystemExit(f"replace --dropped: prop types {unknown} are not this town's Meshy props")
    foot_ok, snap = grounded_rule(ctx), ground_snapper(ctx, device, rock_embed)
    for x in pl["instances"]:
        cover(ctx, x)
    if parity:
        print("PARITY", json.dumps(snap_parity(ctx, pl["instances"], todo[0]["prop"], foot_ok)), flush=True)
    still, placed = [], []
    for old in todo:
        t0 = time.time()
        best = pick(ctx, pl["instances"] + placed, prop=old["prop"], foot_ok=foot_ok, snap=snap, cands=WIDE_CANDS,
                    batched=True)
        tried = {"cands": WIDE_CANDS, "snapRefused": ctx["snapRefused"], "device": snap.device,
                 "best": None if best is None else round(best[0], 1), "seconds": round(time.time() - t0, 1)}
        if best is None or best[0] < MIN_GAIN:
            still.append({**old, "replaceTried": f"{why}: no grounded, snapped candidate gains {MIN_GAIN} px",
                          "search": tried})
            print(f"-- {old['prop']:10s} no candidate {json.dumps(tried)}", flush=True)
            continue
        gain, inst, per = best
        inst.update({"gain": round(gain, 1), "perPose": per, "search": tried,
                     "replacedFrom": {"base": old["base"], "yaw": old["yaw"], "height": old["height"],
                                      "dropped": old.get("why", ""), "why": why}})
        placed.append(inst)
        cover(ctx, inst)
        print(f"{len(pl['instances']) + len(placed) - 1:2d} {inst['prop']:10s} gain {gain:8.0f} h {inst['height']:.2f} "
              f"snap {inst['snapM']:+.2f} m elev {elevation(ctx['views'], inst['base']):.2f}", flush=True)
    pl.setdefault("replaced", []).extend({**x, "fromDropped": True, "why": why} for x in todo if x not in still)
    pl["instances"] += placed
    pl["dropped"] = still
    summary = {"replaced": len(placed), "stillDropped": len(still), "instances": len(pl["instances"]),
               "rockEmbed": ROCK_EMBED_MAX if rock_embed else None, "dryRun": dry_run}
    if dry_run:                 # a trial: nothing is written
        print(json.dumps(summary))
        return pl
    p.write_text(json.dumps(pl, indent=1), encoding="utf-8")
    overlays(ctx, pl["instances"])
    print(json.dumps(summary))
    return pl


def replace(ids: list, why: str) -> dict:
    """Re-place the given instances in place (same index and prop type, place's height rule): the others stay fixed and
    their cover is taken first, then each one is re-picked by place's own score (pick) from place's base pool (which
    already applies the ELEV_MIN rule), refusing every candidate whose foot overhangs a drop at more than FLOAT_MAX
    share at rest or at any pose (check's grounded rule, on the scene without props). An id with no candidate that
    gains MIN_GAIN fails closed and the placement is left unchanged. The old instance goes to placement.json
    "replaced" with the reason."""
    p = PROPS_DIR / "placement.json"
    pl = json.loads(p.read_text(encoding="utf-8"))
    n = len(pl["instances"])
    if not ids or any(k < 0 or k >= n for k in ids) or len(set(ids)) != len(ids):
        raise SystemExit(f"replace: --ids must be distinct instance indices below {n}, got {ids}")
    ctx = place_context()
    unknown = sorted({pl["instances"][k]["prop"] for k in ids} - set(ctx["models"]))
    if unknown:
        raise SystemExit(f"replace: prop types {unknown} are not this town's Meshy props")
    foot_ok = grounded_rule(ctx)
    keep = [x for k, x in enumerate(pl["instances"]) if k not in set(ids)]
    for x in keep:
        cover(ctx, x)
    new = {}
    for k in ids:
        old = pl["instances"][k]
        best = pick(ctx, keep + list(new.values()), prop=old["prop"], foot_ok=foot_ok)
        if best is None or best[0] < MIN_GAIN:
            raise SystemExit(f"replace: instance {k} ({old['prop']}): no grounded candidate gains {MIN_GAIN} px; "
                             "placement unchanged")
        gain, inst, per = best
        inst.update({"gain": round(gain, 1), "perPose": per, "replacedFrom": {"base": old["base"],
                     "yaw": old["yaw"], "height": old["height"], "why": why}})
        new[k] = inst
        cover(ctx, inst)
        print(f"{k:2d} {inst['prop']:10s} gain {gain:8.0f} h {inst['height']:.2f} elev "
              f"{elevation(ctx["views"], inst['base']):.2f}", flush=True)
    pl.setdefault("replaced", []).extend({**pl["instances"][k], "index": k, "why": why} for k in ids)
    for k, inst in new.items():
        pl["instances"][k] = inst
    p.write_text(json.dumps(pl, indent=1), encoding="utf-8")
    overlays(ctx, pl["instances"])
    return pl


# ------------------------------------------------------------------------------------------------ stage
def lin(tex: np.ndarray) -> np.ndarray:
    return G.SC_srgb_to_lin(np.asarray(tex, np.float32) / 255.0)


def gain_match(sc, mdl: dict, spec: dict, paint: np.ndarray) -> np.ndarray:
    """Linear per-channel gain of the Meshy texture so that the prop lit by the Hex/Lit rig matches the painting's
    colour of the same material in its crop (over the faces facing the rest camera; the rig's shadow side is
    near black, so a median over every face would inflate the gain): the crop px nearest the lit prop's median chromaticity (the closest
    GAIN_PX_SHARE; the crop also holds sky / neighbours), median over median, clamped GAIN_CLAMP, and each channel
    kept within GAIN_CHROMA of the mean gain (the concept already took its hue from the painting)."""
    import conflux_full3d_env as E
    x0, y0, x1, y1 = spec["rectFrame"]
    crop = lin(paint[y0:y1, x0:x1].reshape(-1, 3))
    tl = lin(mdl["tex"])
    th, tw = tl.shape[:2]
    uc = mdl["uv"][mdl["F"]].mean(1)
    tx = np.clip((uc[:, 0] % 1.0) * tw, 0, tw - 1).astype(int)
    ty = np.clip((1 - uc[:, 1] % 1.0) * th, 0, th - 1).astype(int)
    fn = mdl["N"][mdl["F"]].mean(1)
    fn /= np.linalg.norm(fn, axis=1, keepdims=True) + 1e-12
    lit = tl[ty, tx] * E.light(fn.astype(np.float32), sc.rig, sc.sun)
    seen = fn @ -np.asarray(sc.cam["fwd"], np.float64) > 0.2    # the faces the camera sees (yaw-averaged below)
    lm = np.median(lit[seen], 0) if seen.sum() > 50 else np.median(lit, 0)
    chrom = lambda c: c / (c.sum(-1, keepdims=True) + 1e-6)
    d = np.linalg.norm(chrom(crop) - chrom(lm[None]), axis=1)
    near = crop[d <= np.quantile(d, GAIN_PX_SHARE)]
    g = np.clip(np.median(near, 0) / np.maximum(lm, 1e-4), *GAIN_CLAMP)
    gm = float(g.mean())
    return np.clip(g, gm * (1 - GAIN_CHROMA), gm * (1 + GAIN_CHROMA))


def stage() -> dict:
    town = SC.FACTION
    if f"homm3_{town}" not in (GEN.BUDGET.get("towns") or []):
        # the props block's pass / meshyCredits come from GEN's group budget (TOWN_T2_PROPS_GROUP); staging a town
        # under a group that does not own it records the wrong pass and 0 credits (cove ssr_dfix, 2026-10-01)
        raise SystemExit(f"town_t2_props stage: budget pass {GEN.PASS} does not cover homm3_{town}; "
                         f"set TOWN_T2_PROPS_GROUP to the group whose budget lists it")
    pl = json.loads((PROPS_DIR / "placement.json").read_text(encoding="utf-8"))
    sc = S.Scene()
    paint = np.asarray(S.homm3_reference(SC.FP.STATES["full"]))
    env = S.PREFIX + "environment"
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    rows[env]["bins"] = [b for b in rows[env]["bins"] if not b["name"].startswith("Mesh_Prop_")]
    for stale in (S.STAGE / env).glob("Mesh_Prop_*"):
        stale.unlink()
    S.ROWS.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    types = {}
    for prop, spec in pl["types"].items():
        insts = [i for i in pl["instances"] if i["prop"] == prop]
        if not insts:
            continue
        mdl = load_prop(Path(spec["glb"]))
        g = gain_match(sc, mdl, spec, paint)
        tex = G.lin_to_srgb(np.clip(lin(mdl["tex"]) * g, 0, 1))
        Ps, Ns, UVs, Fs = [], [], [], []
        for i in insts:
            R = rot_y(i["yaw"])
            Ps.append(instance_world(mdl, i))
            Ns.append(mdl["N"] @ R.T)
            UVs.append(mdl["uv"])
            Fs.append(mdl["F"] + sum(len(p) for p in Ps[:-1]))
        name = f"Mesh_Prop_{prop}"
        sc.add_bin(env, name, np.concatenate(Ps), np.concatenate(Ns), np.concatenate(UVs), np.concatenate(Fs),
                   (np.clip(tex, 0, 1) * 255).astype(np.uint8), srgb=True, max_size=2048, preview=False)
        types[prop] = {"instances": len(insts), "gainLinear": [round(float(x), 3) for x in g],
                       "tris": int(len(mdl["F"]) * len(insts)), "bin": name}
    S.save_rows(sc)
    rp = S.WORK / "stage_report.json"
    rep = json.loads(rp.read_text(encoding="utf-8"))
    credits = props_credits(town)
    block = {"schema": "town_t2_props.v1", "pass": GEN.PASS, "types": types, "instances": len(pl["instances"]),
             "placement": str((PROPS_DIR / "placement.json").relative_to(SC.ROOT)).replace("\\", "/"),
             "meshyCredits": credits, "source": "HoMM3 town painting crops -> Meshy nano-banana-2 concept -> "
                                                  "meshy-t2 image-to-3d (town_t2_props_gen.py)",
             "proofTier": "generated artifact (offline placement + staging)"}
    block["shipped"] = bool(types)
    rep["props"] = block
    rp.write_text(json.dumps(rep, indent=1), encoding="utf-8")
    cat = S.write_catalog(sc, carry="previous", drop=("props",))   # props: re-decided here
    if types:
        cat["props"] = block
    # else every prop was dropped: the environment ships no Mesh_Prop_* bin and the catalog no props block (the spend
    # stays in the ledger, the drops in placement.json, the block with shipped false in stage_report["props"])
    (S.OUT / "catalog.json").write_text(json.dumps(cat, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(block, indent=1))
    return block


def props_credits(town: str) -> int:
    tot = 0
    for line in GEN.LEDGER.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r.get("pass") == GEN.PASS and r.get("faction") == f"homm3_{town}":
                tot += int(r.get("credits", 0))
    return tot


# ------------------------------------------------------------------------------------------------ check
def placement_sha(pl: dict) -> str:
    """sha256 of placement.json's instances: check.json names the prop set its instance ids index."""
    import hashlib
    return hashlib.sha256(json.dumps(pl["instances"], sort_keys=True).encode("utf-8")).hexdigest()


def staged_agrees(pl: dict) -> None:
    """Fail closed unless the staged Mesh_Prop_* bins and the catalog's props block are placement.json's instances
    (Fortress 2026-10-02: a fork whose placement had been cut to 2 instances still staged and catalogued the seed's
    21, so check measured one prop set while the scene shipped another). Per type: the staged bin's triangles are
    vertices are instances x the model's (a later lane may drop faces, never
    vertices: Fortress ssr_v1's fern bin 8 x 3851 verts, 8618 of 8 x 3232 tris), no bin for a type without instances, and catalog["props"] lists the same counts."""
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    env = S.PREFIX + "environment"
    staged = {b["name"][len("Mesh_Prop_"):]: b for b in rows[env]["bins"] if b["name"].startswith("Mesh_Prop_")}
    want = {}
    for i in pl["instances"]:
        want[i["prop"]] = want.get(i["prop"], 0) + 1
    errs = []
    for prop in sorted(set(staged) | set(want)):
        n = want.get(prop, 0)
        if prop not in staged:
            errs.append(f"{prop}: {n} placed, no Mesh_Prop_{prop} staged")
            continue
        if not n:
            errs.append(f"{prop}: Mesh_Prop_{prop} staged, 0 placed")
            continue
        v, _, _, subs = S.read_bin(S.STAGE / env / f"Mesh_Prop_{prop}.bytes")
        mdl = load_prop(Path(pl["types"][prop]["glb"]))
        tris = sum(len(x) for x in subs) // 3
        if len(v) != n * len(mdl["V"]) or tris > n * len(mdl["F"]):
            errs.append(f"{prop}: staged {len(v)} verts / {tris} tris != {n} placed x {len(mdl['V'])} verts "
                        f"(<= x {len(mdl['F'])} tris)")
    cat = json.loads((S.OUT / "catalog.json").read_text(encoding="utf-8"))
    ct = {k: int(v["instances"]) for k, v in ((cat.get("props") or {}).get("types") or {}).items()}
    if ct != want:
        errs.append(f"catalog props {ct} != placement {want}")
    if errs:
        raise SystemExit("town_t2_props check: the staged props are not placement.json's (re-run stage): "
                         + "; ".join(errs))


def check() -> int:
    pl = json.loads((PROPS_DIR / "placement.json").read_text(encoding="utf-8"))
    staged_agrees(pl)
    sc = S.Scene()
    P, UV, F, owner, names, texs, env = scene_buffers(sc)
    # the staged Mesh_Prop_* bins are these very instances: as occluders they z-fight their own placed copy and win
    # the tie, so a visible instance counted ~0 px (Castle zs_v6 2026-10-01: shrub 0 measured 211 px, ~1700 px drawn
    # over the refitted longhouse 3 at rest). The instances are rasterised from placement.json only.
    noprop = np.array([not n.startswith("environment/Mesh_Prop_") for n in names])
    F_occ = F[noprop[owner]]
    Pi, Fi, ii = [], [], []
    off = 0
    for k, i in enumerate(pl["instances"]):
        mdl = load_prop(Path(pl["types"][i["prop"]]["glb"]))
        v = instance_world(mdl, i)
        Pi.append(v)
        Fi.append(mdl["F"] + off)
        ii.append(np.full(len(mdl["F"]), k))
        off += len(v)
    rect = np.zeros((H, W), bool)
    rect[:SC.TH, :SC.TW] = True
    # rest visibility in every build state of the HoMM3 tree, not the full state alone: a prop a building hides in
    # the full state stands in front of the painting while that building is unbuilt (Castle zs_v5 2026-10-01: shrub 3
    # hidden by the tavern upgrade in full, 1354-2288 px over the painted cottages in start / anim)
    import town_full3d_build_states as BS
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    vis, worst = {k: 0 for k in range(len(pl["instances"]))}, {}
    for st, ls in BS.enumerate_states(SC.FP, SC.layer_map()).items():
        Ps_, _, Fs_, ow_, nm_, _ = SM.load_bins(sc, rows, [S.PREFIX + "environment"] + [S.PREFIX + l for l in ls])
        npr = np.array([not n.startswith("environment/Mesh_Prop_") for n in nm_])
        Fo = Fs_[npr[ow_]]
        fid_inst = np.concatenate([np.full(len(Fo), -1)] + ii)
        _, fid = TP.zbuffer(sc.cam, np.concatenate([Ps_] + Pi), np.concatenate([Fo] + [f + len(Ps_) for f in Fi]),
                            sup=1)
        inst = np.where(fid >= 0, fid_inst[np.maximum(fid, 0)], -1)
        for k in vis:
            n = int(((inst == k) & rect).sum())
            if n > vis[k]:
                vis[k], worst[k] = n, st
    bad = {k: v for k, v in vis.items() if v > REST_VISIBLE_MAX}
    floating = grounded(sc, P, F_occ, pl)   # owner is per face (town_t2_streak_map.load_bins)
    low = below_eye(sc, pl["instances"])
    rep = {"placementSha": placement_sha(pl), "instances": len(pl["instances"]), "restVisiblePxInsideRect": vis, "worstState": worst, "max": REST_VISIBLE_MAX, "bad": bad,
           "outsideRectPx": int(((inst >= 0) & ~rect).sum()),
           "overhang": floating, "floatMax": FLOAT_MAX,
           "floating": {k: v for k, v in floating.items() if max(v.values()) > FLOAT_MAX},
           "elevationDeg": low, "elevMin": ELEV_MIN}
    for k, e in low.items():
        if e < ELEV_MIN:
            rep["floating"].setdefault(k, {})["minElevationDeg"] = e
    rep["kept"] = {k: {**rep["floating"].pop(k), "why": pl["instances"][k]["keepReason"]}
                   for k in list(rep["floating"]) if pl["instances"][k].get("keepReason")}
    rep["exempt"] = apply_float_exempt(SC.FACTION, rep["floating"], pl["instances"])
    (PROPS_DIR / "check.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps({"bad": bad, "floating": rep["floating"], "exempt": rep["exempt"],
                      "outsideRectPx": rep["outsideRectPx"], "instances": len(vis)}))
    return 1 if bad or rep["floating"] else 0


def elevation(cams: dict, base) -> float:
    """Smallest angle (deg) by which the cameras look down on a point."""
    b = np.asarray(base, np.float64)
    out = []
    for c in cams.values():
        d = np.asarray(c["pos"], np.float64) - b
        out.append(math.degrees(math.atan2(d[1], math.hypot(d[0], d[2]))))
    return min(out)


def below_eye(sc, instances) -> dict:
    cams = {"rest": sc.cam, **{p: c for p, c in S.pan_cams(sc).items() if p in POSES}}
    return {k: round(elevation(cams, i["base"]), 2) for k, i in enumerate(instances)}


def grounded(sc, P, F, pl) -> dict:
    """Per instance and view (rest + POSES): the share of its foot points that overhang a drop (see check)."""
    cams = {"rest": sc.cam, **{p: c for p, c in S.pan_cams(sc).items() if p in POSES}}
    zs = {v: TP.zbuffer(c, P, F, sup=1)[0] for v, c in cams.items()}
    out = {}
    for k, i in enumerate(pl["instances"]):
        mdl = load_prop(Path(pl["types"][i["prop"]]["glb"]))
        foot = instance_world(mdl, i, np.nonzero(mdl["V"][:, 1] <= FOOT_SHARE)[0])
        per = {}
        for v, cam in cams.items():
            px, py, zc = T.project(cam, foot)
            ok = (zc > 1) & (px >= 0) & (px < W) & (py >= 0) & (py + BELOW_PX < H)
            if not ok.any():
                continue
            zb = zs[v][(py[ok] + BELOW_PX).astype(int), px[ok].astype(int)]
            over = ~np.isfinite(zb) | (zb > zc[ok] * DROP_RATIO)
            per[v] = round(float(over.mean()), 3)
        out[k] = per or {"none": 0.0}
    return out


def drop(why: dict) -> None:
    ids = list(why)
    p = PROPS_DIR / "placement.json"
    pl = json.loads(p.read_text(encoding="utf-8"))
    out = [k for k in ids if not 0 <= k < len(pl["instances"])]
    if out:
        raise SystemExit(f"town_t2_props drop: ids {out} not in placement.json's {len(pl['instances'])} instances")
    pl.setdefault("dropped", []).extend({**pl["instances"][k], "why": why[k]} for k in ids)
    pl["instances"] = [x for k, x in enumerate(pl["instances"]) if k not in set(ids)]
    p.write_text(json.dumps(pl, indent=1), encoding="utf-8")


def apply_float_exempt(town: str, floating: dict, instances: list) -> dict:
    """Pop from `floating` (check's {instance id: reasons}) every instance FLOAT_EXEMPT_APPROVED names whose only
    reason is the elevation term at the pinned minElevationDeg; returns them with the approved reason. An instance
    with any overhanging view, or at another elevation, stays floating (and is printed as refused)."""
    out = {}
    for k in list(floating):
        ex = float_exempt(town, instances[k])
        if ex is None:
            continue
        f = floating[k]
        if set(f) != {"minElevationDeg"} or abs(f["minElevationDeg"] - ex["minElevationDeg"]) > FLOAT_EXEMPT_ELEV_TOL:
            print(json.dumps({"floatExemptRefused": k, "prop": instances[k]["prop"], "floating": f,
                              "pinned": ex["minElevationDeg"]}))
            continue
        out[k] = {**floating.pop(k), "why": ex["reason"]}
    return out


def restore_exempt() -> list:
    """Move every dropped instance that FLOAT_EXEMPT_APPROVED names (town, prop, pinned base) back into the
    placement, unchanged (recorded in placement.json "restored"). Fails closed when none matches. Re-run stage and
    check afterwards: check exempts only the pinned elevation term."""
    p = PROPS_DIR / "placement.json"
    pl = json.loads(p.read_text(encoding="utf-8"))
    keep, back = [], []
    for d in pl.get("dropped", []):
        ex = float_exempt(SC.FACTION, d)
        (back if ex is not None else keep).append(d)
    if not back:
        raise SystemExit(f"restore-exempt: no dropped instance of {SC.FACTION} matches FLOAT_EXEMPT_APPROVED")
    for d in back:
        inst = {k: v for k, v in d.items() if k not in ("why", "replaceTried", "search")}
        pl["instances"].append(inst)
        pl.setdefault("restored", []).append({"prop": d["prop"], "base": d["base"], "droppedWhy": d.get("why"),
                                              "exemption": float_exempt(SC.FACTION, d)["reason"]})
    pl["dropped"] = keep
    p.write_text(json.dumps(pl, indent=1), encoding="utf-8")
    return back


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["place", "stage", "check", "drop-bad", "keep", "drop", "replace",
                                    "restore-exempt"])
    ap.add_argument("--ids", default="")
    ap.add_argument("--why", default="")
    ap.add_argument("--max", type=int, default=30)
    ap.add_argument("--dropped", action="store_true", help="replace: re-place every dropped instance (wide search, "
                    "ground snap) instead of --ids")
    ap.add_argument("--device", choices=["cpu", "cuda"], default=None,
                    help="replace --dropped: the ground snap's device (default TOWN_FULL3D_DEVICE / cuda)")
    ap.add_argument("--parity", action="store_true", help="replace --dropped: first check the batched cuda snap and "
                    "pick against the per-candidate cpu reference (PARITY_CANDS draws), fail closed on a difference")
    ap.add_argument("--rock-embed", action="store_true", help="replace --dropped: ROCK_FORMATIONS props may bury their "
                    "uphill side up to ROCK_EMBED_MAX of their height (instead of SNAP_SINK_MAX)")
    ap.add_argument("--dry-run", action="store_true", help="replace --dropped: report only, write nothing")
    a = ap.parse_args()
    if not S.CANDIDATE:
        raise SystemExit("set TOWN_FULL3D_CANDIDATE")
    if a.cmd == "place":
        place(a.max)
        return 0
    if a.cmd == "stage":
        stage()
        return 0
    if a.cmd == "restore-exempt":
        print(json.dumps({"restored": [{"prop": d["prop"], "base": d["base"]} for d in restore_exempt()]}))
        return 0
    if a.cmd == "keep":
        if not a.ids or not a.why:
            raise SystemExit("keep: --ids and --why are required")
        p = PROPS_DIR / "placement.json"
        pl = json.loads(p.read_text(encoding="utf-8"))
        for k in (int(x) for x in a.ids.split(",")):
            pl["instances"][k]["keepReason"] = a.why
        p.write_text(json.dumps(pl, indent=1), encoding="utf-8")
        return 0
    if a.cmd == "drop":
        if not a.ids or not a.why:
            raise SystemExit("drop: --ids and --why are required")
        drop({int(x): f"by eye: {a.why}" for x in a.ids.split(",")})
        return 0
    if a.cmd == "replace" and a.dropped:
        if a.ids or not a.why:
            raise SystemExit("replace --dropped: --why is required and --ids is not taken")
        replace_dropped(a.why, a.device, a.parity, a.rock_embed, a.dry_run)
        return 0
    if a.cmd == "replace":
        if not a.ids or not a.why:
            raise SystemExit("replace: --ids and --why are required")
        replace([int(x) for x in a.ids.split(",")], a.why)
        return 0
    if a.cmd == "drop-bad":
        rep = json.loads((PROPS_DIR / "check.json").read_text(encoding="utf-8"))
        pl = json.loads((PROPS_DIR / "placement.json").read_text(encoding="utf-8"))
        if rep.get("placementSha") != placement_sha(pl):
            # check.json's ids index the placement it measured; after a drop / replace / a fork that placement is gone
            # (Fortress 2026-10-02: a second drop-bad on the seed's 21-instance check.json raised IndexError on 2)
            raise SystemExit(f"drop-bad: check.json (placementSha {rep.get('placementSha')}, "
                             f"{len(rep.get('restVisiblePxInsideRect', {}))} instances) is not the current placement "
                             f"({len(pl['instances'])} instances): run stage and check first")
        why = {int(k): "rest-visible inside the painted rect (check)" for k in rep["bad"]}
        why.update({int(k): f"floats: foot overhangs a drop {v} (check)" for k, v in rep.get("floating", {}).items()})
        drop(why)
        return 0
    return check()


if __name__ == "__main__":
    raise SystemExit(main())
