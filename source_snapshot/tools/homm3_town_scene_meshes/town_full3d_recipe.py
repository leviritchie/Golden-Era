#!/usr/bin/env python3
"""Town full-3D: declarative per-town recipe to a zero-visible-streak candidate (methodology v2 option H).

    python town_full3d_recipe.py build  tools/homm3_town_scene_meshes/recipes/<town>_<name>.json
    python town_full3d_recipe.py verify tools/homm3_town_scene_meshes/recipes/<town>_<name>.json

The recipe (schema town_full3d_recipe.v1, docs/homm3_town_scene_methodology_v2.md "Recipe") names a seed candidate
and the steps, all of which already exist as measured lanes; `build` runs them in order on a fresh candidate and
fails closed unless the zero-streak certificate passes at the end:

  1. seed      stronghold_full3d_scene.py candidate-init --seed-from <seed> (refuses an existing candidate; it
               inherits the seed's pins and catalog blocks, fail-closed: town_full3d_fork.py);
  2. ldi       with ldi.fromPreLdi, first town_full3d_ldi.py unlayer: a seed that is itself an LDI candidate (whose
               later fixes - building depth, seams, cloth - are wanted) gets its pre-LDI terrain back exactly from its
               own record, fail-closed; then town_full3d_ldi.py apply on the recipe's pieces, with the view-set bound back rule (--back-rule vlb),
               no hole keeping, cut and closed against the certificate's reachable set (--reach-loop);
  3. backstop  one frame-wide sheet on the rest camera's rays behind the environment's rest surface (Mesh_Backstop),
               inverse depth the largest L-Lipschitz function under it (L = (K-1) / (f * b_max) per px: by the
               view-set bound it cannot stretch past K at any reachable pose), extended past the frame border by each
               border's own parallax. It is behind the environment alone, so it is hidden at rest in every town state
               (a state without a building shows the environment there, never the sheet);
  4. repair    certificate rounds over every town state: a face in a visible behind-streak component that no state
               shows at rest is dropped (the backstop shows where it opened); any other failing face becomes a card
               (vertices slid along their rest rays to its farthest forward depth: a fronto-parallel card is a pure
               scale at every pose). A card that still streaks (its own uv: a near-edge-on sliver at rest) is held
               while other faces are repaired; when only such cards are left and the recipe allows rule planar, it
               is laid planar (its uv the chart's affine rest px -> uv map: isotropic, a pure scale at every pose);
               a card already planar that still fails fails the build. Only the rules the recipe allows run; a failing face no allowed rule covers
               (a Meshy front, which needs the bake's front predicate) fails the build. repair.seamAware (opt-in):
               a residual face with a vertex within SEAM_GUARD_PX of its Meshy body's rest silhouette is neither
               dropped nor carded (it carries the seams_v1 seam); when only such faces still fail the build fails
               closed. Castle zs_v3 (2026-10-01) fails that way: its streaking faces are its seam faces.
               repair rule flap (needs drop and card; town_full3d_step_flap.py): a failing face of a residual bin
               that bridges a depth step (STEP_EPS) is torn out even when seam-guarded (drop / card as above), and
               the far side of the step gets a flap at its own depth on the near side's rest rays, hidden at rest
               by the layer's own front (FLAP_HIDE), over the reachable opening only, with the residual's own
               texels mirrored across the lip (its affine rest px -> uv map, fail-closed). Castle zs_v4 passes
               both the certificate and seams_v1 this way;
               repair rule planar (v2, unseen-face term) re-lays a face's uv from its bin's rest px -> uv chart maps; a
               bin with no such chart (the periphery's polar atlas) sends its unseen faces to rule drop instead, and so
               does a face that still stretches with planar uv (a rest-ray sliver), only when drop is allowed and no
               state shows them at rest (round records planarNoMapDropped / planarRefailDropped);
  5. content   sky-side prune first: a backstop triangle that only pose rays missing the painted floor plane inside
               the far cap meet (the certificate's dome rule) is removed, so the dome shows there instead of a band
               of ground paint behind the horizon. Then the backstop's texture: the environment's own rest colour where the sheet touches the rest surface
               (within TOUCH of its inverse depth: the sheet IS the far surface there), verbatim wherever no pose sees
               it, and where a reachable pose sees the sheet behind an occluder, image quilting (town_full3d_ldi.
               quilt_fill) from far-side ground texels only (touching, within ground_src_m of the painted floor plane;
               a roof or wall that touches the sheet is not ground's far side). No generative model;
  6. gate      certificate.extraPoses (optional): named sweep samples (loop_NNN) added to the loop's poses for the
               repair rounds and this gate, e.g. the poses an earlier full certificate run failed at; or the value
               "final" (opt-in, v2): the repair rounds, the prune and this gate certify `final`'s own pose set
               (reachable_cams_full(sc, FINAL_LOOP)) from the start, so the build sees every pose `final` judges;
               the certificate (town_full3d_zero_streak.certify) on the staged bins, every state: pass = zero
               visible behind components at every pose, and no ground hole beyond the state's rest count. The
               result, the recipe sha and a sha over every staged bin it measured go to work/zero_streak_recipe.json
               and the stage report's "zeroStreakRecipe"; `verify` re-hashes the bins (cheap, no raster) and
               tools/validate_town_zero_streak_contract.py runs it for every recipe whose candidate is staged.

  7. catalog   write_catalog on the candidate, carrying over every block of the seed's own catalog that write_catalog
               does not produce (props, sky, water: the lanes that wrote them carry the previous catalog's keys the
               same way; candidate-init forked the seed's catalog as this one's previous catalog). The building-depth terrain sample is
               re-taken from the re-layered terrain here. Bundling (Unity) and validate_town_scene3d_contract stay
               separate steps.

Proof tier: generated artifact (offline raster of the staged bins). The certificate draws lit Mesh_ bins only, no
alpha, no lighting; a pass does not replace the by-eye check in Unity renders, and nothing here bundles or installs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SCHEMA = "town_full3d_recipe.v1"
SCHEMA_V2 = "town_full3d_recipe.v2"   # + build states from the tree, ground contact, unseen-face term (module doc)
SCHEMAS = (SCHEMA, SCHEMA_V2)
RESULT_SCHEMA = "town_full3d_recipe_result.v1"
BACKSTOP_BIN = "Mesh_Backstop"
FINAL_LOOP = 36             # `final`: the sweep samples of the one-time reachable-range gate (43 poses before v2)
RULES = ("drop", "card", "flap", "planar")   # flap: town_full3d_step_flap.py (residual depth steps); planar: v2
TOUCH = 0.9                 # backstop inverse depth >= TOUCH x the rest surface's: the sheet is the far surface there
BACKSTOP_BEHIND = 1.02      # the sheet starts this factor behind the environment's rest surface
MARGIN_MAX_PX = 600         # border extension cap (px) per side
PRUNE_CYCLES = 4            # repair rounds -> sky-side prune cycles before the geometry must be at a fixed point
REANCHOR_CYCLES = 3         # v2: re-anchor -> repair cycles after a repair round left an anchored piece without ground
HALO_PX = 2                 # exemplar texels keep this far from the fill
RECIPE_KEYS = {"schema", "faction", "seed", "candidate", "ldi", "backstop", "repair", "certificate", "decal",
               "groundContact", "restPaint", "peripherySettle", "paintOrder", "restOwner", "edits", "note"}
# v2 only, opt-in: "edits": {"base": "<recipe path>", "ops": ["tools/homm3_town_scene_meshes/town_bench/edits/<faction>/
# <id>.json", ...]} (apply_edits; docs/town_bench.md). Town bench op files, applied in their merge order after the
# content step (5b) and before the gate, so a fix made on the bench is a recipe step: `build` reproduces it from the
# seed and `verify` / the gate certify the result like any other. The recipe must equal its base recipe apart from
# candidate / note / edits (tools/validate_town_bench_contract.py), so the edits are the only difference; an op pins
# the faces it was authored on (facesSha) and fails closed on other geometry.
EDITS_KEYS = {"base", "ops"}
# v2 only, opt-in: "peripherySettle": {"pieces": [Mesh_Outer..], "why"} (periphery_settle). The periphery's own contract
# (stronghold_full3d_periphery.settle: frameIntrusions 0) holds against the terrain it was built on; a later terrain
# change can leave a periphery sheet drawn in front of the frame surface at rest (Dungeon props_v2 2026-10-02:
# Mesh_OuterL1 nearer than the frame in 2972 px of x 0-21, down to 0.69 x its depth). Its uv is the periphery's
# world-space polar chart, no rest projection, so neither the LDI (affine uv) nor a card (a rest-degenerate sliver
# stays one) repairs it there. The step re-applies the periphery's own settle rule against the staged frame surface.
PERIPHERY_SETTLE_KEYS = {"pieces", "why"}
PERIPHERY_PREFIX = "Mesh_Outer"
PERIPHERY_SETTLE_ROUNDS = 8
# v2 only, opt-in: "restOwner": {"layers": [lid..], "why"} (rest_owner). A Meshy T2 body can be drawn at rest where the
# HoMM3 painting shows something else (Fortress zs_v2 2026-10-02, rest-paint): tbfrdw_0_2 / tbfrdw_2 faces outside
# their own sprite (2067 / 768 px, Meshy completed geometry the sprite never had), and tbfrcstl_3's wall in front of
# tbfrhrd2 in `full` (413 + 367 px) although the painting's z order draws the horde building over it. The step makes
# the listed layers' rest ownership agree with the painting's: a face of a listed layer drawn at a rest px outside its
# own sprite (alpha, grown REST_OWNER_GROW_PX) is dropped; one drawn where its sprite is covered by a later layer's
# (positions z order) goes back along its own rest rays behind that layer's surface, so its rest px and uv are kept in
# every state (rest_owner reports each). Relation to "paintOrder" (paint_order_cut, Cove): that cut drops a body face
# in front of a later layer only when every state that builds the body also builds such a layer, and keeps the rest;
# restOwner pushes those kept faces back instead (rest px kept in the state that shows them) and also drops the faces
# outside the layer's own sprite, which paintOrder does not look at. A recipe may use both (paintOrder runs after).
REST_OWNER_KEYS = {"layers", "why"}
REST_OWNER_GROW_PX = 2
REST_OWNER_ROUNDS = 40
REST_OWNER_PLATEAU = 3     # rounds without a new minimum of misowned px end the step (sub-vertex residue; probe on
#                            Fortress zs_v2: 6382 -> 229 px by round 33, then 1-17 vertices a round with no gain)
REST_PAINT_KEYS = {"fxShareOverride", "knownGaps"}     # v2 only: {layer: {"share", "why"}} within REST_PAINT_FX_SHARE_APPROVED
GROUND_CONTACT_KEYS = {"extensionDrop", "removeHidden"}   # v2 only; extensionDrop: town_full3d_ground_contact.extension_drop
# (opt-in); removeHidden: [{bin, piece, verts, why}] environment pieces proven to draw 0 px at rest and every reachable
# pose, dropped before anchoring (town_full3d_ground_contact.remove_hidden; coordinator 2026-10-02)
EDITS_DIR = "tools/homm3_town_scene_meshes/town_bench/edits"
PAINT_ORDER_KEYS: set = set()   # "paintOrder": {} opts in to the build-state painting-order cut (paint_order_cut), v2
PAINT_ORDER_TOL = 0.01      # relative camera-z margin before a face counts as in front of a later-drawn layer
DECAL_KEYS = {"layerDepth"}  # "decal": {} opts in to the sprite ground decals (town_full3d_sprite_decal.py), v2 only;
                             # "layerDepth": {} lays a decal px whose environment is far behind the layer at its depth
LDI_KEYS = {"pieces", "cut", "zone", "backRule", "vlbK", "keepRounds", "reachLoop", "cropAlign", "fromPreLdi"}
BACKSTOP_KEYS = {"K", "stepPx", "groundSrcM", "groundFloor"}
# backstop.groundFloor (v2, opt-in; Inferno zs_v3 2026-10-02): hidden ground behind the near ridge / buildings. The
# certificate's groundHiddenPx counts a pose ray that meets the painted floor plane inside the far cap at a point some
# rest surface hides; the Lipschitz sheet cannot hold it there (next to the painting's sky it is pulled toward
# infinity, and it has no px where the environment draws nothing behind a building). The floor fill is the painted
# floor plane itself as px squares at the coverage edge (floor_fill), in the backstop bin (its uv, so its texels and content step are the
# sheet's): only at in-frame grid px that every build state covers at rest, whose floor point lies FLOOR_FILL_BEHIND
# behind the farthest rest surface of any state over the cell's window, inside the far cap. Hidden at rest by
# construction and checked (fail closed: any fill face drawn at rest in any state).
FLOOR_FILL_BEHIND = 1.05
FLOOR_FILL_BAND_PX = 16
FLOOR_FILL_EPS_PX = 0.05      # outer boundary corners move this far out (rest px; floor_fill)
FLOOR_FILL_EXT_PX = 16       # floor_fill: px past the rest frame on each side (capped by the backstop's margin)
FILL_GROUND_CHUNK = 65536     # fill_ground_faces: vertices per cdist chunk (x ~160 cams x 8 B: ~84 MB)
# the far limit (rest camera distance) is far_cap + the largest rest-to-pose camera displacement of the certified
# cams: the certificate counts ground up to far_cap from the POSE camera, so by the triangle inequality its hit points
# lie within far_cap + |pose - rest| of the rest camera (Inferno: 400 + 18.0 m; a fixed 1.02 x 400 = 408 m left the
# 397 m pose hits at 411 m rest distance uncovered, zs_v3 run 1: 28 px at sweep_fwd)
REPAIR_KEYS = {"rules", "rounds", "seamAware", "seamWeld"}
# seamWeld (opt-in, 2026-10-02; docs/homm3_town_scene_methodology_v2.md "Seam weld"): inside the repair fixed point,
# once the rounds are clean and the prune removes nothing, the validator's seams_v2 measure on the in-memory stage
# (town_full3d_building_seams.rest_seams, load=Stage): the residual face of every split pair between a Meshy body and
# its residual is carded onto the body's rest depth at the pair (per-face copies slid along their rest rays by the
# median body / residual distance ratio of its split pairs; the rest frame keeps every px), up to SEAM_WELD_ITERS
# measure-and-card passes; then the rounds run again to certify the welded geometry, at most SEAM_WELD_CYCLES times.
# Rampart zs_v6 2026-10-02 (offline, seam_weld_exp): 24 / 48 / 40 split pairs on tbrmdw_0 / tbrmhal2 / tbrmhall ->
# 18 / 33 / 20 after two passes; every seed split there was such a Body|BodyRest pair (body_v2 leaves 1-3 % steps)
SEAM_WELD_ITERS = 3
SEAM_WELD_CYCLES = 2
SEAM_GUARD_PX = 2.0         # seamAware: a residual face with a vertex this close (rest frame px) to its body's silhouette
CERT_KEYS = {"loop", "states", "extraPoses"}
# certificate.extraPoses "final" (v2, opt-in; coordinator 2026-10-02 after Stronghold / Necropolis / Bulwark / Dungeon
# each failed a first `final` on poses the build's loop never saw): the build certifies final's pose set (cert_cams_of)
EXTRA_POSES_FINAL = "final"
# v2 rest-paint term (gate): what is drawn at rest equals the HoMM3 painting, in every build state. Chromaticity
# (rgb / (r+g+b)) is compared, since the staged albedo is the painting de-lit by a grey shade, which scales a px's rgb
# and leaves its chromaticity. A px differs when a channel's chromaticity differs by more than REST_PAINT_CHROMA %
# (both px brighter than REST_PAINT_MIN_SUM); the term fails on a 3x3-opened component of REST_PAINT_AREA px or more.
# Calibrated 2026-10-01 on Castle: zs_v5's largest component is 258 px (house edges, the orb glow: registration
# noise); zs_v6's shrub prop over the refitted longhouse 3 at rest is 1695 px, which neither rest identity (fid
# against the pre-anchor frame) nor the props lane's per-instance cap caught.
REST_PAINT_SCHEMA = "town_full3d_rest_paint.v1"
REST_PAINT_CHROMA = 8.0
REST_PAINT_MIN_SUM = 60.0
REST_PAINT_AREA = 400
# Exclusion class (coordinator decision 2026-10-02, not a threshold change): a smoke / steam / fire plume is a DEF
# animation that the scene draws as a particle emitter, not as staged albedo, so the painting's frame-0 plume differs
# from the rest albedo by construction. The term skips exactly the DEF-changed px (town_full3d_fx's own effect mask,
# dilated REST_PAINT_FX_DILATE_PX) of an effect whose kind is in REST_PAINT_FX_KINDS ("flame" = fire; the fx lane has no
# steam kind: steam is classified smoke), on a layer present in the state, and only when that effect's emitter
# (Fx_<Kind>_<k>_* particle group) is staged in the layer's prefab; without the emitter the px count. Per state and
# layer, the build fails closed when the layer's exclusion exceeds REST_PAINT_FX_MAX_PX or REST_PAINT_FX_MAX_SHARE of
# its sprite px, whichever is smaller (coordinator 2026-10-02: 1500 px first; 6000 px after Factory's measured plumes,
# tbfablak 5909 px = 19.8 % of its sprite; the share and the staged emitter are the guard).
REST_PAINT_FX_KINDS = {"smoke": "Fx_Smoke_", "flame": "Fx_Flame_"}
REST_PAINT_FX_DILATE_PX = 2
REST_PAINT_FX_MAX_PX = 6000
REST_PAINT_FX_MAX_SHARE = 0.25
# Per-layer overrides the coordinator approved by name: {(faction, layer): {"share", "pxCap", "reason"}}. The entry's
# share and pxCap replace REST_PAINT_FX_MAX_SHARE / REST_PAINT_FX_MAX_PX for that layer only (the staged emitter is
# still required); a recipe names it under restPaint.fxShareOverride with its own reason, and load_recipe refuses any
# layer not in this table or a share above the entry's. An entry without a reason fails at import.
# 2026-10-02: Bulwark's great pyre (needs 6122 px, 34 %); Necropolis' Cover of Darkness (needs 20055 px, 35 %).
REST_PAINT_FX_SHARE_APPROVED = {
    ("bulwark", "tbbumr01"): {"share": 0.40, "pxCap": 8000, "reason": "pyre layer: painting is mostly its own flame"},
    ("necropolis", "tbncspec"): {"share": 0.40, "pxCap": 21000,
                                 "reason": "Cover of Darkness: painting is mostly its own black smoke"},
}
for _k, _e in REST_PAINT_FX_SHARE_APPROVED.items():
    if set(_e) != {"share", "pxCap", "reason"} or not str(_e["reason"]).strip() or int(_e["pxCap"]) <= 0             or not REST_PAINT_FX_MAX_SHARE < float(_e["share"]) <= 1.0:
        raise SystemExit(f"town recipe: REST_PAINT_FX_SHARE_APPROVED{_k} must be {{share > {REST_PAINT_FX_MAX_SHARE}, "
                         f"pxCap > 0, reason}} (the coordinator's approval, by name)")


# Known rest-paint gaps the coordinator approved by name (2026-10-02, Factory): {(faction, state): {"layer", "maxPx",
# "reason"}}. Only early min_ states are eligible. A recipe lists the entry under restPaint.knownGaps as
# {state, layer, maxPx, why} with maxPx at most the approval's (the measured px plus at most 10 %); in that state every
# component of REST_PAINT_AREA px or more must be drawn mostly by that layer and be at most maxPx, and the state then
# passes, recorded as "knownGap". Any other state, a bigger component, another layer's component, or an entry without
# a reason fails.
REST_PAINT_KNOWN_GAPS_APPROVED = {
    ("factory", "min_tbfacas2"): {"layer": "tbfacas2", "maxPx": 590,
                                  "reason": "Meshy T2 cas2 spire over painted sky; same gap installed in pb_v1"},
    ("bulwark", "min_tbbucstl"): {"layer": "tbbucstl", "maxPx": 1336,
                                  "reason": "Meshy T2 Castle tower crenels over painted sky; same gap installed in pb_v1"},
    ("bulwark", "min_tbbubl01"): {"layer": "tbbucstl", "maxPx": 1336,
                                  "reason": "Meshy T2 Castle tower crenels over painted sky; same gap installed in pb_v1"},
}
for _k, _e in REST_PAINT_KNOWN_GAPS_APPROVED.items():
    if set(_e) != {"layer", "maxPx", "reason"} or not str(_e["reason"]).strip() or int(_e["maxPx"]) <= 0             or not str(_k[1]).startswith("min_"):
        raise SystemExit(f"town recipe: REST_PAINT_KNOWN_GAPS_APPROVED{_k} must be a min_ state with {{layer, maxPx > 0, "
                         f"reason}} (the coordinator's approval, by name)")


def fail(msg: str):
    raise SystemExit(f"town recipe: {msg}")


def load_recipe(path: Path) -> dict:
    r = json.loads(Path(path).read_text(encoding="utf-8"))
    if r.get("schema") not in SCHEMAS:
        fail(f"{path}: schema must be one of {SCHEMAS}")
    for k, keys in (("", RECIPE_KEYS), ("ldi", LDI_KEYS), ("backstop", BACKSTOP_KEYS), ("repair", REPAIR_KEYS),
                    ("certificate", CERT_KEYS), ("decal", DECAL_KEYS), ("groundContact", GROUND_CONTACT_KEYS),
                    ("restPaint", REST_PAINT_KEYS), ("peripherySettle", PERIPHERY_SETTLE_KEYS),
                    ("paintOrder", PAINT_ORDER_KEYS), ("restOwner", REST_OWNER_KEYS)):
        if k in ("decal", "groundContact", "restPaint", "peripherySettle", "paintOrder", "restOwner") and k not in r:
            continue
        d = r if not k else r.get(k)
        if not isinstance(d, dict):
            fail(f"{path}: {k} must be an object")
        extra = set(d) - keys
        if extra:
            fail(f"{path}: unknown {k or 'recipe'} keys {sorted(extra)}")
    for k in ("faction", "seed", "candidate"):
        if not isinstance(r.get(k), str) or not r[k]:
            fail(f"{path}: {k} must be a non-empty string")
    if r["candidate"] == r["seed"]:
        fail(f"{path}: the candidate must differ from its seed")
    ldi = r["ldi"]
    if not ldi.get("pieces") or not all(isinstance(p, str) and p.startswith("Mesh_") for p in ldi["pieces"]):
        fail(f"{path}: ldi.pieces must list environment Mesh_ pieces")
    if not isinstance(ldi.get("fromPreLdi", False), bool):
        fail(f"{path}: ldi.fromPreLdi must be true or false")
    if ldi.get("backRule", "vlb") not in ("vlb", "cap") or ldi.get("cut", "zone") not in ("zone", "smear"):
        fail(f"{path}: ldi.backRule in (vlb, cap), ldi.cut in (zone, smear)")
    if not isinstance(r["repair"].get("seamAware", False), bool):
        fail(f"{path}: repair.seamAware must be true or false")
    if not isinstance(r["repair"].get("seamWeld", False), bool):
        fail(f"{path}: repair.seamWeld must be true or false")
    if r["repair"].get("seamWeld") and r.get("schema") != SCHEMA_V2:
        fail(f"{path}: repair.seamWeld is a v2 step (it measures the building seams of a building-depth pin)")
    bad = [x for x in r["repair"].get("rules", []) if x not in RULES]
    if bad:
        fail(f"{path}: repair.rules {bad} are not stage rules {RULES}")
    if "flap" in r["repair"].get("rules", []) and not {"drop", "card"} <= set(r["repair"]["rules"]):
        fail(f"{path}: repair rule flap tears with drop and card: list both")
    if int(r["certificate"].get("loop", 12)) < 12:
        fail(f"{path}: certificate.loop below 12 does not sample the sweep")
    if r["schema"] == SCHEMA_V2 and r["certificate"].get("states"):
        fail(f"{path}: a {SCHEMA_V2} recipe measures every build state of the tree; certificate.states is v1 only")
    if "groundContact" in r and (r["schema"] != SCHEMA_V2
                                 or not isinstance(r["groundContact"].get("extensionDrop", False), bool)):
        fail(f"{path}: groundContact is a {SCHEMA_V2} step; groundContact.extensionDrop must be true or false")
    rh = r.get("groundContact", {}).get("removeHidden", [])
    if not isinstance(rh, list) or not all(isinstance(e, dict) and set(e) == {"bin", "piece", "verts", "why"}
                                           and isinstance(e["why"], str) and e["why"].strip() for e in rh):
        fail(f"{path}: groundContact.removeHidden must list {{bin, piece, verts, why}} entries, each with a reason")
    for lid, o in (r.get("restPaint", {}).get("fxShareOverride") or {}).items():
        ok_ = (r["schema"] == SCHEMA_V2 and isinstance(o, dict) and set(o) == {"share", "why"}
               and isinstance(o["why"], str) and o["why"].strip() and isinstance(o["share"], (int, float)))
        ap_ = REST_PAINT_FX_SHARE_APPROVED.get((r.get("faction"), lid))
        if not ok_ or ap_ is None or not REST_PAINT_FX_MAX_SHARE < float(o["share"]) <= ap_["share"]:
            fail(f"{path}: restPaint.fxShareOverride[{lid!r}] must be {{share, why}} ({SCHEMA_V2}) with a share above "
                 f"{REST_PAINT_FX_MAX_SHARE} and within the approved entry {ap_} (REST_PAINT_FX_SHARE_APPROVED: only "
                 f"layers the coordinator approved by name)")
        o["pxCap"], o["approvedReason"] = int(ap_["pxCap"]), ap_["reason"]     # the px cap is the approval's
    kg = r.get("restPaint", {}).get("knownGaps", [])
    seen_kg = set()
    for e in kg if isinstance(kg, list) else [None]:
        ap_ = REST_PAINT_KNOWN_GAPS_APPROVED.get((r.get("faction"), e.get("state"))) if isinstance(e, dict) else None
        if not (r["schema"] == SCHEMA_V2 and isinstance(e, dict) and set(e) == {"state", "layer", "maxPx", "why"}
                and isinstance(e["why"], str) and e["why"].strip() and str(e["state"]).startswith("min_")
                and isinstance(e["maxPx"], int) and ap_ is not None and e["layer"] == ap_["layer"]
                and 0 < e["maxPx"] <= ap_["maxPx"] and e["state"] not in seen_kg):
            fail(f"{path}: restPaint.knownGaps entry {e!r} must be {{state, layer, maxPx, why}} ({SCHEMA_V2}) for a "
                 f"min_ state the coordinator approved by name (REST_PAINT_KNOWN_GAPS_APPROVED: {ap_}), once, with "
                 f"maxPx within the approval")
        seen_kg.add(e["state"])
        e["approvedMaxPx"], e["approvedReason"] = int(ap_["maxPx"]), ap_["reason"]
    ed = r.get("edits")
    if ed is not None and not (r["schema"] == SCHEMA_V2 and isinstance(ed, dict) and set(ed) == EDITS_KEYS
                               and isinstance(ed["base"], str) and ed["base"].endswith(".json")
                               and isinstance(ed["ops"], list) and ed["ops"]
                               and all(isinstance(x, str) and x.startswith(f"{EDITS_DIR}/{r.get('faction')}/")
                                       and x.endswith(".json") for x in ed["ops"])
                               and len(set(ed["ops"])) == len(ed["ops"])):
        fail(f"{path}: edits is a {SCHEMA_V2} step: {{base: <recipe .json>, ops: [{EDITS_DIR}/<faction>/<id>.json, "
             f"...] (distinct, at least one)}}")
    if "paintOrder" in r and r["schema"] != SCHEMA_V2:
        fail(f"{path}: paintOrder is a {SCHEMA_V2} step (it measures the build-state tree)")
    ps = r.get("peripherySettle")
    if ps is not None and not (r["schema"] == SCHEMA_V2 and isinstance(ps.get("pieces"), list) and ps["pieces"]
                               and all(isinstance(x, str) and x.startswith(PERIPHERY_PREFIX) for x in ps["pieces"])
                               and isinstance(ps.get("why"), str) and ps["why"].strip()):
        fail(f"{path}: peripherySettle is a {SCHEMA_V2} step: {{pieces: [{PERIPHERY_PREFIX}..], why}}")
    ro = r.get("restOwner")
    if ro is not None and not (r["schema"] == SCHEMA_V2 and isinstance(ro.get("layers"), list) and ro["layers"]
                               and len(set(ro["layers"])) == len(ro["layers"])
                               and all(isinstance(x, str) and x for x in ro["layers"])
                               and isinstance(ro.get("why"), str) and ro["why"].strip()):
        fail(f"{path}: restOwner is a {SCHEMA_V2} step: {{layers: [distinct layer ids], why}}")
    if "groundFloor" in r["backstop"] and (r["schema"] != SCHEMA_V2
                                           or not isinstance(r["backstop"]["groundFloor"], bool)):
        fail(f"{path}: backstop.groundFloor is a {SCHEMA_V2} step and must be true or false")
    if "decal" in r and r["schema"] != SCHEMA_V2:
        fail(f"{path}: decal is a {SCHEMA_V2} step (the rest-paint term is what it answers)")
    xp = r["certificate"].get("extraPoses", [])
    if xp == EXTRA_POSES_FINAL:
        if r["schema"] != SCHEMA_V2:
            fail(f"{path}: certificate.extraPoses \"{EXTRA_POSES_FINAL}\" is a {SCHEMA_V2} value")
        return r
    if not isinstance(xp, list) or not all(isinstance(x, str) and x.startswith(("loop_", "cursor_", "free_", "transition_"))
                                           for x in xp):
        fail(f"{path}: certificate.extraPoses must list poses of the reachable range (loop_NNN, cursor_cN, free_..., "
             f"transition_NNN; zero_streak.reachable_cams resolves them and fails on an unknown name)")
    return r


def recipe_sha(path: Path) -> str:
    """sha256 of the recipe file with CRLF read as LF (core.autocrlf checkouts must not change a recipe's identity)."""
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


# ------------------------------------------------------------------------------------------------ build steps 1-2
def _env(r: dict) -> dict:
    return {**os.environ, "TOWN_FULL3D_FACTION": r["faction"], "TOWN_FULL3D_CANDIDATE": r["candidate"]}


def _run(cmd: list, env: dict) -> None:
    print("RUN", " ".join(str(c) for c in cmd), flush=True)
    p = subprocess.run([sys.executable, *map(str, cmd)], env=env, cwd=str(ROOT))
    if p.returncode:
        fail(f"step failed ({p.returncode}): {' '.join(str(c) for c in cmd)}")


def build(path: Path) -> int:
    r = load_recipe(path)
    env = _env(r)
    _run([HERE / "stronghold_full3d_scene.py", "candidate-init", "--faction", r["faction"], "--seed-from", r["seed"]],
         env)
    import importlib
    sys.path.insert(0, str(HERE))
    os.environ["TOWN_FULL3D_FACTION"] = r["faction"]
    SC = importlib.import_module("stronghold_full3d_common")
    ldi = r["ldi"]
    if ldi.get("fromPreLdi"):
        _run([HERE / "town_full3d_ldi.py", "--faction", r["faction"], "unlayer", "--npz",
              SC.DATA / "candidates" / r["seed"] / "bundle" / "terrain_streak.npz"], env)
    cmd = [HERE / "town_full3d_ldi.py", "--faction", r["faction"], "apply", "--pieces", ",".join(ldi["pieces"]),
           "--cut", ldi.get("cut", "zone"), "--back-rule", ldi.get("backRule", "vlb"),
           "--vlb-k", ldi.get("vlbK", 2.0), "--keep-rounds", ldi.get("keepRounds", 0),
           "--reach-loop", ldi.get("reachLoop", 12), "--crop-align", ldi.get("cropAlign", 1)]
    if ldi.get("zone"):
        cmd += ["--zone", json.dumps(ldi["zone"])]
    _run(cmd, env)
    _run([Path(__file__).resolve(), "_finish", path], env)
    _run([Path(__file__).resolve(), "_catalog", path], env)
    return 0


def catalog(path: Path) -> int:
    sys.path.insert(0, str(HERE))
    import stronghold_full3d_scene as S
    import town_full3d_fork as FK
    r = load_recipe(path)
    if S.CANDIDATE != r["candidate"]:
        fail(f"catalog: TOWN_FULL3D_CANDIDATE is {S.CANDIDATE!r}, the recipe's candidate is {r['candidate']!r}")
    prev = S.OUT / "catalog.json"        # the seed's catalog as candidate-init forked it (town_full3d_fork)
    if not prev.is_file():
        fail(f"catalog: {prev} is missing: the seed had no catalog to carry its blocks from")
    old = json.loads(prev.read_text(encoding="utf-8"))
    cat = S.write_catalog(S.Scene(), carry="previous")
    carried = FK.carry_catalog(cat, old)
    (S.OUT / "catalog.json").write_text(json.dumps(cat, indent=1) + "\n", encoding="utf-8")
    print("CATALOG", S.OUT / "catalog.json", "carried from the seed:", carried, flush=True)
    return 0


# ------------------------------------------------------------------------------------------------ in-candidate steps
class Stage:
    """Every lit, unposed Mesh_ bin of the given prefabs, editable per face (drop, card) and written back in place."""

    def __init__(self, S, SM, sc, rows: dict, keys: list):
        self.S, self.sc, self.bins = S, sc, []
        for k in keys:
            for b in rows.get(k, {}).get("bins", []):
                if not b["name"].startswith("Mesh_") or b.get("kind", "lit") != "lit" or b.get("pos") or b.get("rot"):
                    continue
                p = S.STAGE / k / f"{b['name']}.bytes"
                v, n, uv, subs = S.read_bin(p)
                sid = np.concatenate([np.full(len(s), i, np.int32) for i, s in enumerate(subs)]) if subs else \
                    np.zeros(0, np.int32)
                self.bins.append({"key": k, "name": b["name"], "path": p, "v": np.asarray(v, np.float64),
                                  "n": np.asarray(n, np.float64), "uv": np.asarray(uv, np.float64),
                                  "f": np.concatenate(subs).reshape(-1, 3).astype(np.int64) if subs else
                                  np.zeros((0, 3), np.int64), "sid": sid, "nsub": len(subs),
                                  "tex": SM.png_size(S.STAGE / k / f"{b['name']}_albedo.png"), "dirty": False})
                if b.get("colors"):
                    # lit cloth (town_full3d_cloth.py): one RGBA per vertex in <bin>.vcol; card and planar append
                    # vertices, so the colours follow them (Castle zs_v6 2026-10-01: planar on two cloth bins left
                    # 3447 colours for 3498 vertices and the Unity bundle build refused it)
                    col = np.frombuffer((S.STAGE / k / f"{b['name']}.vcol").read_bytes(), np.float32).reshape(-1, 4)
                    if len(col) != len(v):
                        fail(f"{k}/{b['name']}: {len(col)} vertex colours for {len(v)} vertices before any repair")
                    self.bins[-1]["col"] = col.copy()

    def arrays(self, keys=None):
        """World P, UV, F, owner, names, texs (the certificate's form) and the face -> (bin, local face) map."""
        to_world = lambda v: self.sc.cpos + (v / self.sc.scale) @ self.sc.C.T
        Ps, UVs, Fs, owner, names, texs, fmap = [], [], [], [], [], [], []
        off = 0
        for bi, b in enumerate(self.bins):
            if keys is not None and b["key"] not in keys:
                continue
            Fs.append(b["f"] + off)
            Ps.append(to_world(b["v"]))
            UVs.append(b["uv"])
            owner.append(np.full(len(b["f"]), len(names), np.int32))
            names.append(f"{b['key'][len(self.S.PREFIX):]}/{b['name']}")
            texs.append(b["tex"])
            fmap.append(np.stack([np.full(len(b["f"]), bi), np.arange(len(b["f"]))], 1))
            off += len(b["v"])
        return (np.concatenate(Ps), np.concatenate(UVs), np.concatenate(Fs), np.concatenate(owner), names,
                np.asarray(texs, np.float64), np.concatenate(fmap))

    def normals(self, keys) -> np.ndarray:
        return np.concatenate([b["n"] for b in self.bins if b["key"] in keys])

    def drop(self, bi: int, lf: np.ndarray) -> None:
        b = self.bins[bi]
        keep = np.ones(len(b["f"]), bool)
        keep[lf] = False
        b["f"], b["sid"], b["dirty"] = b["f"][keep], b["sid"][keep], True

    def card(self, bi: int, lf: np.ndarray) -> None:
        """Per-face vertex copies slid along the rest rays (prefab-local: camera at the origin, z = forward depth) to
        the face's farthest forward depth; same uv and normal, so the rest frame keeps the face's paint."""
        b = self.bins[bi]
        tri = b["v"][b["f"][lf]]                                    # (n, 3, 3)
        z = np.maximum(tri[..., 2], 1e-9)
        card = tri * (z.max(1, keepdims=True) / z)[..., None]
        off = len(b["v"])
        b["v"] = np.concatenate([b["v"], card.reshape(-1, 3)])
        b["n"] = np.concatenate([b["n"], b["n"][b["f"][lf]].reshape(-1, 3)])
        if "col" in b:
            b["col"] = np.concatenate([b["col"], b["col"][b["f"][lf]].reshape(-1, 4)])
        if "vMap" in b:                         # rule flap's per-vertex chart map follows the copies
            b["vMap"] = np.concatenate([b["vMap"], b["vMap"][b["f"][lf]].ravel()])
        b["uv"] = np.concatenate([b["uv"], b["uv"][b["f"][lf]].reshape(-1, 2)])
        b["f"] = b["f"].copy()
        b["f"][lf] = off + np.arange(3 * len(lf)).reshape(-1, 3)
        b["dirty"] = True

    def card_at(self, bi: int, lf: np.ndarray, factor: np.ndarray) -> None:
        """Rule card with a given slide per face vertex (repair.seamWeld): per-face vertex copies scaled along their
        rest rays by factor (n, 3) (prefab-local: the rest camera at the origin, so a scale is a slide along the ray);
        same uv and normal, so the rest frame keeps the face's paint."""
        b = self.bins[bi]
        tri = b["v"][b["f"][lf]] * np.asarray(factor, np.float64)[..., None]
        off = len(b["v"])
        b["v"] = np.concatenate([b["v"], tri.reshape(-1, 3)])
        b["n"] = np.concatenate([b["n"], b["n"][b["f"][lf]].reshape(-1, 3)])
        if "col" in b:
            b["col"] = np.concatenate([b["col"], b["col"][b["f"][lf]].reshape(-1, 4)])
        if "vMap" in b:
            b["vMap"] = np.concatenate([b["vMap"], b["vMap"][b["f"][lf]].ravel()])
        b["uv"] = np.concatenate([b["uv"], b["uv"][b["f"][lf]].reshape(-1, 2)])
        b["f"] = b["f"].copy()
        b["f"][lf] = off + np.arange(3 * len(lf)).reshape(-1, 3)
        b["dirty"] = True

    def geometry_sha(self) -> str:
        """sha256 over what the certificate reads of every bin (vertices, uv, faces, in bin order). Normals and
        textures are not in it: the certificate never reads them."""
        h = hashlib.sha256()
        for b in self.bins:
            for a in (b["v"], b["uv"], b["f"]):
                a = np.ascontiguousarray(a)
                h.update(f"{b['key']}/{b['name']}:{a.dtype.str}{a.shape}".encode() + a.tobytes())
        return h.hexdigest()

    def require_certified(self, sha: str, step: str) -> None:
        """Fail closed when the geometry differs from the one the last clean repair round certified: a step after the
        repair rounds must not change what the gate measures without a new round (Rampart zs_v1, 2026-10-01: the
        sky-side prune ran after the last round and exposed periphery faces no round had seen)."""
        if self.geometry_sha() != sha:
            fail(f"{step}: the staged geometry changed after the last clean repair round (re-certify it in a round)")

    def planar(self, bi: int, lf: np.ndarray, A: np.ndarray) -> None:
        """Rule planar (v2, the unseen-face term): per-face vertex copies at the same positions (the rest frame keeps
        every px), uv re-laid flat on the face's own plane at the rest texel density, centred on the face's own rest
        px: a face the rest camera never sees takes the paint around where it stands (the building's own wall) one
        texel per rest px, instead of the rest projection smeared across it. A: the bin's affine rest px -> uv map
        (town_full3d_step_flap.uv_affine, fail-closed). Per-face math on the device (TOWN_FULL3D_DEVICE; cpu is the
        reference), elementwise as town_full3d_ground_contact._xp. A may also be one map per face ((len(lf), 3, 2): the
        bin's chart maps, town_full3d_step_flap.uv_affine_charts)."""
        import town_full3d_ground_contact as GC
        import town_gpu_kernels as GK
        import stronghold_full3d_terrain as T
        X = GC._xp(GK.resolve_device(None))
        b = self.bins[bi]
        sc = self.sc
        cam = sc.cam
        tri = X.arr((sc.cpos + (b["v"][b["f"][lf]].reshape(-1, 3) / sc.scale) @ sc.C.T).reshape(-1, 3, 3))
        c = (tri[:, 0] + tri[:, 1] + tri[:, 2]) * (1.0 / 3.0)

        def cross(u, v):
            return (u[:, 1] * v[:, 2] - u[:, 2] * v[:, 1], u[:, 2] * v[:, 0] - u[:, 0] * v[:, 2],
                    u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0])

        def unit(x, y, z):
            ln = X.maximum(X.sqrt(x * x + y * y + z * z), 1e-12)
            return X.div(x, ln), X.div(y, ln), X.div(z, ln)

        def stack(x, y, z):
            return (X.t.stack((x, y, z), 1) if X.cuda else np.stack((x, y, z), 1))

        def dot(u, v):
            return u[:, 0] * float(v[0]) + u[:, 1] * float(v[1]) + u[:, 2] * float(v[2])

        n = stack(*unit(*cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])))
        # e1 = up x n, horizontal in the face's plane; a horizontal face takes the camera's right, in its plane
        e1x, e1z = n[:, 2] * 1.0, -n[:, 0]
        e1y = n[:, 0] * 0.0
        r = [float(x) for x in cam["right"]]
        nr = dot(n, r)
        flat = X.sqrt(e1x * e1x + e1z * e1z) < 1e-3
        e1x = X.where(flat, r[0] - nr * n[:, 0], e1x)
        e1y = X.where(flat, r[1] - nr * n[:, 1], e1y)
        e1z = X.where(flat, r[2] - nr * n[:, 2], e1z)
        e1 = stack(*unit(e1x, e1y, e1z))
        e1 = e1 * X.where(dot(e1, r) < 0, -1.0, 1.0)[:, None]            # left to right as the rest frame reads
        e2 = stack(*cross(n, e1))
        e2 = e2 * X.where(dot(e2, cam["up"]) < 0, -1.0, 1.0)[:, None]
        d = c - X.arr(np.asarray(cam["pos"], np.float64))
        cz = dot(d, cam["fwd"])
        tn = math.tan(math.radians(cam["fov"]) / 2)
        cx = (X.div(dot(d, cam["right"]), X.div(cz * tn * T.W, T.H)) + 1) * 0.5 * T.W
        cy = (1 - X.div(dot(d, cam["up"]), cz * tn)) * 0.5 * T.H
        k = X.div(0.5 * T.H / tn, X.maximum(cz, 1e-9))                    # rest px per metre at the face's depth
        A = np.asarray(A, np.float64)
        if A.ndim == 2:
            A_ = [[float(x) for x in row] for row in A]
        else:
            A_ = [[X.arr(np.ascontiguousarray(A[:, r, i])) for i in range(2)] for r in range(3)]
        uvs = []
        for j in range(3):
            dj = tri[:, j] - c
            qx = cx + (dj[:, 0] * e1[:, 0] + dj[:, 1] * e1[:, 1] + dj[:, 2] * e1[:, 2]) * k
            qy = cy - (dj[:, 0] * e2[:, 0] + dj[:, 1] * e2[:, 1] + dj[:, 2] * e2[:, 2]) * k
            uvs.append([qx * A_[0][i] + qy * A_[1][i] + A_[2][i] for i in range(2)])
        uv = np.stack([np.stack([X.np(uvs[j][i]) for i in range(2)], 1) for j in range(3)], 1).reshape(-1, 2)
        off = len(b["v"])
        b["v"] = np.concatenate([b["v"], b["v"][b["f"][lf]].reshape(-1, 3)])
        b["n"] = np.concatenate([b["n"], b["n"][b["f"][lf]].reshape(-1, 3)])
        if "col" in b:
            b["col"] = np.concatenate([b["col"], b["col"][b["f"][lf]].reshape(-1, 4)])
        if "vMap" in b:                         # rule flap's per-vertex chart map follows the copies
            b["vMap"] = np.concatenate([b["vMap"], b["vMap"][b["f"][lf]].ravel()])
        b["uv"] = np.concatenate([b["uv"], uv])
        b["f"] = b["f"].copy()
        b["f"][lf] = off + np.arange(3 * len(lf)).reshape(-1, 3)
        b["planar"] = set(b.get("planar") or set()) | set(int(x) for x in lf)
        b["dirty"] = True

    def write(self) -> list:
        out, cloth = [], {}
        for b in self.bins:
            if not b["dirty"]:
                continue
            subs = [b["f"][b["sid"] == i] for i in range(b["nsub"])]
            self.S.write_bin(b["path"], b["v"], b["n"], b["uv"], subs)
            out.append(f"{b['key']}/{b['name']}")
            if "col" in b:
                if len(b["col"]) != len(b["v"]):
                    fail(f"{b['key']}/{b['name']}: {len(b['col'])} vertex colours for {len(b['v'])} vertices")
                vc = b["path"].with_suffix(".vcol")
                vc.write_bytes(np.ascontiguousarray(b["col"], np.float32).tobytes())
                cloth[(b["key"], b["name"])] = (hashlib.sha256(vc.read_bytes()).hexdigest(), len(b["v"]))
        if cloth:
            # the cloth block pins each piece's colour file and vertex count (its catalog_block fails closed on them)
            sp = self.S.WORK / "stage_report.json"
            sr = json.loads(sp.read_text(encoding="utf-8"))
            for p in (sr.get("cloth") or {}).get("pieces", []):
                hit = cloth.pop((p["prefab"], p["piece"]), None)
                if hit:
                    p["colorsSha256"], p["verts"] = hit
            if cloth:
                fail(f"vertex colours written for {sorted(cloth)} that the stage report's cloth block does not declare")
            sp.write_text(json.dumps(sr, indent=1, default=float), encoding="utf-8")
        return out


def lipschitz_backstop(sc, TP, z_env: np.ndarray, cams: dict, K: float, step: int, far_cap: float) -> dict:
    """Step 3's geometry on a step-px grid of rest-frame px (extended past each border by its own parallax): world
    vertices, triangles, the inverse-depth image wb and the bound's constants."""
    import cv2
    h, w = z_env.shape
    ok = np.isfinite(z_env) & (z_env > 0)
    w0 = np.where(ok, 1.0 / np.where(ok, z_env, 1.0), 0.0) / BACKSTOP_BEHIND
    t = math.tan(math.radians(sc.cam["fov"]) / 2)
    f_px = (h / 2) / t
    c0 = np.asarray(sc.cam["pos"], np.float64)
    bmax = max(float(np.hypot((np.asarray(c["pos"]) - c0) @ sc.cam["right"], (np.asarray(c["pos"]) - c0) @ sc.cam["up"]))
               for c in cams.values())
    if bmax <= 0:
        fail("backstop: the reachable set has no lateral baseline")
    L = (K - 1.0) / (f_px * bmax) / math.sqrt(2.0)          # 8-neighbour steps: the diagonal is the bound
    wb = w0.astype(np.float32)
    ker = np.ones((3, 3), np.uint8)
    for _ in range(8000):
        nb = np.minimum(wb, cv2.erode(wb, ker) + np.float32(L))
        if np.array_equal(nb, wb):
            break
        wb = nb
    else:
        fail("backstop: Lipschitz envelope did not converge")
    # a translated pose sees past a border by the parallax of what it looks at there (f x baseline x inverse depth)
    side = {"top": wb[0], "bottom": wb[-1], "left": wb[:, 0], "right": wb[:, -1]}
    m = {k: int(min(MARGIN_MAX_PX, math.ceil(f_px * bmax * float(a.max()) / step) * step + step)) for k, a in side.items()}
    ys, xs = np.mgrid[-m["top"]:h + m["bottom"] + 1:step, -m["left"]:w + m["right"] + 1:step]
    gw = wb[np.clip(ys, 0, h - 1), np.clip(xs, 0, w - 1)].astype(np.float64)
    zf = np.where(gw > 1e-9, 1.0 / np.maximum(gw, 1e-12), np.inf)
    zf = np.minimum(zf, far_cap)
    xn = ((xs + 0.5) / w * 2 - 1) * t * w / h
    yn = (1 - (ys + 0.5) / h * 2) * t
    d = sc.cam["fwd"][None, None] + xn[..., None] * sc.cam["right"][None, None] + yn[..., None] * sc.cam["up"][None, None]
    V = c0[None, None] + d * zf[..., None]
    gh, gw_ = ys.shape
    idx = np.arange(gh * gw_).reshape(gh, gw_)
    a, b, c, e = idx[:-1, :-1], idx[:-1, 1:], idx[1:, :-1], idx[1:, 1:]
    tris = np.concatenate([np.stack([a, c, b], -1).reshape(-1, 3), np.stack([b, c, e], -1).reshape(-1, 3)])
    has = (gw > 1e-9).ravel()
    tris = tris[has[tris].all(1)]
    tw, th = w + m["left"] + m["right"], h + m["top"] + m["bottom"]
    uv = np.stack([(xs + m["left"] + 0.5) / tw, 1 - (ys + m["top"] + 0.5) / th], -1).reshape(-1, 2)
    touch = (wb >= TOUCH * w0) & (w0 > 0)
    return {"V": V.reshape(-1, 3), "uv": uv, "tris": tris, "wb": wb, "w0": w0, "touch": touch, "margin": m,
            "grid": (gh, gw_),
            "texSize": (tw, th), "gridPx": np.stack([xs, ys], -1).reshape(-1, 2),
            "report": {"K": K, "L": L, "bmaxWorld": bmax, "fPx": f_px, "stepPx": step, "marginPx": m,
                       "tris": int(len(tris)), "verts": int(len(V.reshape(-1, 3))), "texture": [tw, th]}}


def _bins_world(stage: "Stage", bis: list):
    """World P and F of the given stage bins, with the bin index of every face."""
    sc = stage.sc
    Ps, Fs, own, off = [], [], [], 0
    for bi in bis:
        b = stage.bins[bi]
        Ps.append(sc.cpos + (b["v"] / sc.scale) @ sc.C.T)
        Fs.append(b["f"] + off)
        own.append(np.full(len(b["f"]), bi, np.int64))
        off += len(b["v"])
    if not Ps:
        return np.zeros((0, 3)), np.zeros((0, 3), np.int64), np.zeros(0, np.int64)
    return np.concatenate(Ps), np.concatenate(Fs), np.concatenate(own)


def periphery_settle(sc, T, TP, stage: "Stage", env_key: str, pieces: list, apply: bool = True) -> dict:
    """The periphery's settle rule (stronghold_full3d_periphery.settle: kept vertices go back along their own rest ray
    to PUSH_REL / PUSH_ABS behind the frame surface) re-applied against the staged frame surface: every environment
    bin that is not periphery (not Mesh_Outer*) and not the backstop, z-buffered at rest. A rest px where a listed
    piece is drawn nearer than that surface, or where there is no frame surface (sky), is an intrusion. Each round
    moves the vertices of the faces drawn at intrusion px along their own rest rays behind the farthest frame surface
    (3x3-conservative) over the px the face intrudes at and at the vertex's own rest px; the rest px of every vertex
    is kept, uv and normals are untouched. Fails closed when a listed piece is not staged, when a listed piece is
    drawn where the frame has no surface (an intrusion into the sky has no settle depth), or when
    intrusions remain after PERIPHERY_SETTLE_ROUNDS. apply=False only measures (the intrusion px every v2 recipe
    reports). Raster: moderngl (TP.zbuffer); the per-vertex move is a few hundred scalars (CPU, no kernel)."""
    import cv2
    import stronghold_full3d_periphery as PE
    from stronghold_full3d_common import W, H
    want = set(pieces)
    pis = [bi for bi, b in enumerate(stage.bins) if b["key"] == env_key and b["name"] in want]
    if apply and {stage.bins[bi]["name"] for bi in pis} != want:
        fail(f"peripherySettle: pieces {sorted(want - {stage.bins[bi]['name'] for bi in pis})} are not staged "
             f"environment bins")
    frame = [bi for bi, b in enumerate(stage.bins) if b["key"] == env_key and not b["name"].startswith(PERIPHERY_PREFIX)
             and b["name"] != BACKSTOP_BIN]
    Pf, Ff, _ = _bins_world(stage, frame)
    zF, fF = TP.zbuffer(sc.cam, Pf, Ff, sup=1)
    has = fF >= 0
    # conservative frame depth: the farthest surface within 3x3 px (the periphery's frame_depth_grid takes the max
    # over 3x3 vertices); px with no frame surface stay empty
    zFd = np.where(has, cv2.dilate(np.where(has, zF, 0.0).astype(np.float32), np.ones((3, 3), np.uint8)), np.nan)
    rep = {"pieces": sorted(stage.bins[bi]["name"] for bi in pis), "pushRel": PE.PUSH_REL, "pushAbsM": PE.PUSH_ABS,
           "rounds": []}
    for rnd in range(PERIPHERY_SETTLE_ROUNDS + 1):
        Pp, Fp, own = _bins_world(stage, pis)
        if not len(Fp):
            rep["rounds"].append({"intrusionPx": 0, "overSkyPx": 0, "byPiece": {}})
            break
        zA, fA = TP.zbuffer(sc.cam, Pp, Fp, sup=1)
        drawn = fA >= 0
        intr = drawn & (~has | (zA < zF))
        oi = own[fA[intr]]
        row = {"intrusionPx": int(intr.sum()), "overSkyPx": int((drawn & ~has).sum()),
               "byPiece": {stage.bins[bi]["name"]: int((oi == bi).sum()) for bi in pis if (oi == bi).any()}}
        rep["rounds"].append(row)
        if not intr.any() or not apply:
            break
        if rnd == PERIPHERY_SETTLE_ROUNDS:
            fail(f"peripherySettle: {row['intrusionPx']} intrusion px remain after {PERIPHERY_SETTLE_ROUNDS} rounds "
                 + json.dumps(row))
        if row["overSkyPx"]:
            fail(f"peripherySettle: {row['overSkyPx']} px of {row['byPiece']} are drawn where the frame has no surface "
                 "(an intrusion into the sky has no settle depth)")
        # the settle depth of an intruding face: the farthest frame surface (3x3-conservative) over the px it intrudes
        # at; a vertex goes behind the deepest of its intruding faces and of its own rest px. 1/z is affine across a
        # face on screen, so a face whose vertices are all behind a depth is behind it at every interior px
        fz = np.full(len(Fp), -np.inf)
        np.maximum.at(fz, fA[intr], zFd[intr])
        moved = 0
        offs = np.cumsum([0] + [len(stage.bins[bi]["f"]) for bi in pis])
        for j, bi in enumerate(pis):
            b = stage.bins[bi]
            fzb = fz[offs[j]:offs[j + 1]]
            lf = np.flatnonzero(np.isfinite(fzb))
            if not len(lf):
                continue
            vt = np.full(len(b["v"]), -np.inf)
            for k in range(3):
                np.maximum.at(vt, b["f"][lf, k], fzb[lf])
            vv = np.flatnonzero(np.isfinite(vt))
            px, py, zc = T.project(sc.cam, sc.cpos + (b["v"][vv] / sc.scale) @ sc.C.T)
            if (zc <= 0).any():
                fail(f"peripherySettle: {b['name']}: {int((zc <= 0).sum())} intruding vertices lie behind the rest camera")
            xi = np.clip(np.floor(px), 0, W - 1).astype(np.int64)
            yi = np.clip(np.floor(py), 0, H - 1).astype(np.int64)
            zf = np.fmax(vt[vv], zFd[yi, xi])          # own px may be off the frame surface (clamped border px)
            zt = zf * (1 + PE.PUSH_REL) + PE.PUSH_ABS
            go = zc < zt
            if go.any():
                b["v"] = b["v"].copy()
                b["v"][vv[go]] *= (zt[go] / zc[go])[:, None]   # prefab-local: the rest camera is the origin
                b["dirty"] = True
                moved += int(go.sum())
        row["verticesMoved"] = moved
        if not moved:
            fail("peripherySettle: intrusion px remain but no vertex is in front of its settle depth "
                 "(sub-vertex intrusion inside a face) " + json.dumps(row))
    rep["intrusionPxBefore"] = rep["rounds"][0]["intrusionPx"]
    rep["intrusionPxAfter"] = rep["rounds"][-1]["intrusionPx"]
    rep["verticesMoved"] = int(sum(x.get("verticesMoved", 0) for x in rep["rounds"]))
    return rep


def rest_owner(S, SC, T, TP, sc, stage: "Stage", layers_of: dict, lids: list) -> dict:
    """The restOwner step (REST_OWNER_*). Per build state that shows a listed layer A: the rest z-buffer of the state's
    bins (no backstop; rest_colour), and the painting's owner per frame px (the sprites composited in positions z
    order, alpha above town_full3d_sprite_decal.ALPHA_MIN; -1 where only the background shows). A rest px inside the
    painted rect that the rest-paint term counts as differing (chroma, min sum, 3x3 open), drawn by A, where the
    painting's owner is not A (A's owner px grown REST_OWNER_GROW_PX) is misowned:
      - outside A's own sprite (grown the same): the face is not part of the HoMM3 building in any state -> dropped;
      - inside it, under a later layer B: A's vertices of the face go back along their own rest rays behind B's rest
        surface there (3x3-conservative, the periphery's PUSH_REL / PUSH_ABS); rest px and uv are kept in every
        state. A px where B has no rest surface is counted (noOwnerSurfacePx) and left to the rest-paint term.
    Rounds to a fixed point, or stops after REST_OWNER_PLATEAU rounds without a new minimum (the residue is reported:
    misownedPxAfter, and the rest-paint term still gates it); fails closed when a listed layer is in no build state,
    or when the rounds reach REST_OWNER_ROUNDS. Raster: moderngl (TP.zbuffer); the owner composite and the per-vertex
    moves are array ops on a few masks / vertices (CPU: no raster, no kernel)."""
    import cv2
    import stronghold_full3d_periphery as PE
    import town_full3d_sprite_decal as DC
    W, H, TW, TH = SC.W, SC.H, SC.TW, SC.TH
    lays = SC.layers()
    unknown = sorted(l for l in lids if not any(l in ls for ls in layers_of.values()))
    if unknown:
        fail(f"restOwner: layers {unknown} are in no build state")
    alpha = {l: DC.frame_layer(SC, S, l)[0] > DC.ALPHA_MIN for l in {l for ls in layers_of.values() for l in ls}}
    ker = np.ones((2 * REST_OWNER_GROW_PX + 1,) * 2, np.uint8)

    def grow(m):
        return cv2.dilate(m.astype(np.uint8), ker).astype(bool)

    own_spr = {l: grow(alpha[l]) for l in lids}
    rect = np.zeros((H, W), bool)
    rect[:TH, :TW] = True
    pre = S.PREFIX
    states = [s for s, ls in layers_of.items() if set(ls) & set(lids)]
    rep = {"layers": list(lids), "growPx": REST_OWNER_GROW_PX, "pushRel": PE.PUSH_REL, "pushAbsM": PE.PUSH_ABS,
           "states": states, "rounds": []}
    dropped = {l: 0 for l in lids}
    pushed = {l: 0 for l in lids}
    refs = {}
    best, since = float("inf"), 0
    rep["stop"] = "fixedPoint"
    for rnd in range(REST_OWNER_ROUNDS + 1):
        row = {"misownedPx": {}, "outsidePx": {}, "coveredPx": {}, "noOwnerSurfacePx": {}}
        drop_f, push_f = set(), {}
        for st in states:
            ls = layers_of[st]
            order = sorted(ls, key=lambda l: lays[l].get("z", 0))
            top = np.full((H, W), -1, np.int64)
            for i, l in enumerate(order):
                top[alpha[l]] = i
            ks = [S.ENV_KEY] + [pre + l for l in ls]
            bis = [bi for bi, b in enumerate(stage.bins) if b["key"] in ks and b["name"] != BACKSTOP_BIN]
            # the rest-paint term's own px test (chroma, min sum, 3x3 open) on this state's rest albedo
            # no albedo cache across states / rounds: the float32 images of every state's bins held together ran the
            # host out of memory (Fortress zs_v2 2026-10-02, 5 builds in flight); each state reads its own once
            rgb, _, ok, _, fid, _, _ = rest_colour(sc, T, TP, stage, ks, None, want_fid=True)
            if st not in refs:
                refs[st] = np.asarray(S.homm3_reference(list(ls)), np.float32)
            ref = refs[st]
            sa, sr = rgb.sum(-1), ref.sum(-1)
            d = np.abs(rgb / np.maximum(sa, 1e-6)[..., None] - ref / np.maximum(sr, 1e-6)[..., None]).max(-1) * 100
            differs = cv2.morphologyEx((ok & (sa > REST_PAINT_MIN_SUM) & (sr > REST_PAINT_MIN_SUM)
                                        & (d > REST_PAINT_CHROMA)).astype(np.uint8), cv2.MORPH_OPEN,
                                       np.ones((3, 3), np.uint8)).astype(bool)
            fmap = stage.arrays(ks)[6]
            ob = np.full((H, W), -1, np.int64)
            ob[ok] = fmap[fid[ok], 0]
            lfp = np.full((H, W), -1, np.int64)
            lfp[ok] = fmap[fid[ok], 1]
            for a in [l for l in lids if l in ls]:
                ia = order.index(a)
                mine = [bi for bi in bis if stage.bins[bi]["key"] == pre + a]
                mis = rect & differs & np.isin(ob, mine) & ~grow(top == ia)
                if not mis.any():
                    continue
                out = mis & ~own_spr[a]
                cov = mis & own_spr[a] & (top > ia)
                k = f"{st}/{a}"
                row["misownedPx"][k], row["outsidePx"][k], row["coveredPx"][k] = \
                    int(mis.sum()), int(out.sum()), int(cov.sum())
                drop_f.update(zip(ob[out].tolist(), lfp[out].tolist()))
                nos = 0
                for ib in np.unique(top[cov]):
                    bl = order[int(ib)]
                    here = cov & (top == ib)
                    bbis = [bi for bi in bis if stage.bins[bi]["key"] == pre + bl]
                    Pb, Fb, _ = _bins_world(stage, bbis)
                    if not len(Fb):
                        nos += int(here.sum())
                        continue
                    zB, fB = TP.zbuffer(sc.cam, Pb, Fb, sup=1)
                    hasB = fB >= 0
                    zBd = cv2.dilate(np.where(hasB, zB, 0.0).astype(np.float32), np.ones((3, 3), np.uint8))
                    nos += int((here & ~hasB).sum())
                    ys, xs = np.nonzero(here & hasB)
                    for key, zt in zip(zip(ob[ys, xs].tolist(), lfp[ys, xs].tolist()), zBd[ys, xs].tolist()):
                        push_f[key] = max(push_f.get(key, 0.0), zt)
                if nos:
                    row["noOwnerSurfacePx"][k] = nos
            del rgb, ok, fid, differs, ob, lfp, top
        for key in drop_f:
            push_f.pop(key, None)
        row["facesDropped"], row["facesPushed"] = len(drop_f), len(push_f)
        for bi in sorted({b for b, _ in drop_f}):
            lf = np.array([f for b, f in drop_f if b == bi], np.int64)
            stage.drop(bi, lf)
            dropped[stage.bins[bi]["key"][len(pre):]] += len(lf)
        moved = 0
        for bi in sorted({b for b, _ in push_f}):
            b = stage.bins[bi]
            items = [(lf, zt) for (bb, lf), zt in push_f.items() if bb == bi]
            lf = np.array([x[0] for x in items], np.int64)
            zf = np.array([x[1] for x in items], np.float64)
            vt = np.full(len(b["v"]), -np.inf)
            for kk in range(3):
                np.maximum.at(vt, b["f"][lf, kk], zf)
            vv = np.flatnonzero(np.isfinite(vt))
            _, _, zc = T.project(sc.cam, sc.cpos + (b["v"][vv] / sc.scale) @ sc.C.T)
            if (zc <= 0).any():
                fail(f"restOwner: {b['key']}/{b['name']}: {int((zc <= 0).sum())} vertices lie behind the rest camera")
            zt = vt[vv] * (1 + PE.PUSH_REL) + PE.PUSH_ABS
            go = zc < zt
            if go.any():
                b["v"] = b["v"].copy()
                b["v"][vv[go]] *= (zt[go] / zc[go])[:, None]   # prefab-local: the rest camera is the origin
                b["dirty"] = True
                moved += int(go.sum())
                pushed[b["key"][len(pre):]] += int(go.sum())
        row["verticesMoved"] = moved
        rep["rounds"].append(row)
        print("REST OWNER", rnd, json.dumps({"misownedPx": sum(row["misownedPx"].values()),
                                             "noOwnerSurfacePx": sum(row["noOwnerSurfacePx"].values()),
                                             "facesDropped": len(drop_f), "facesPushed": len(push_f),
                                             "verticesMoved": moved}), flush=True)
        if not drop_f and not moved:
            break
        cur = sum(row["misownedPx"].values())
        if cur < best:
            best, since = cur, 0
        else:
            since += 1
        if since >= REST_OWNER_PLATEAU:
            rep["stop"] = "plateau"
            break
        if rnd == REST_OWNER_ROUNDS:
            fail(f"restOwner: misowned px remain after {REST_OWNER_ROUNDS} rounds " + json.dumps(row))
    last = rep["rounds"][-1]
    rep.update({"misownedPxBefore": sum(rep["rounds"][0]["misownedPx"].values()),
                "misownedPxAfter": sum(last["misownedPx"].values()),
                "noOwnerSurfacePxAfter": dict(last["noOwnerSurfacePx"]),
                "facesDropped": dropped, "verticesPushed": pushed})
    return rep


def rest_cover(sc, TP, stage: "Stage", state_keys: dict, device: str) -> tuple:
    """(covered in every build state at rest, the farthest rest depth of any state) per rest px. device cuda:
    town_gpu_kernels.Raster (byte-identical to TP.zbuffer, test_town_gpu_kernels); cpu: TP.zbuffer (the reference)."""
    cover, zmax, ras = None, None, None
    try:
        for s, ks in state_keys.items():
            P, UV, F, owner, names, texs, fmap = stage.arrays(ks)
            if device == "cuda":
                import town_gpu_kernels as GK
                if ras is None:
                    GK.require_cuda()
                    ras = GK.Raster(P, F)
                else:
                    ras.load(P, F)
                z, fid = ras.render(sc.cam)
            elif device == "cpu":
                z, fid = TP.zbuffer(sc.cam, P, F, sup=1)
            else:
                fail(f"rest_cover: device {device!r} is not cpu or cuda")
            drawn = fid >= 0
            zs = np.where(drawn, z, 0.0).astype(np.float64)
            cover = drawn if cover is None else cover & drawn
            zmax = zs if zmax is None else np.maximum(zmax, zs)
    finally:
        if ras is not None:
            ras.release()
    return cover, zmax


def floor_fill(sc, T, B: dict, cover: np.ndarray, zmax: np.ndarray, far_cap: float, cams: dict,
               behind: float = FLOOR_FILL_BEHIND, band: int = FLOOR_FILL_BAND_PX):
    """backstop.groundFloor's geometry (BACKSTOP_KEYS note): the painted floor plane as the union of the rest-frame
    px squares of the valid px. A px is valid when every state covers its centre at rest and the floor point on its
    centre's ray lies `behind` x the farthest rest surface any state draws there, within far_cap + the cams' reach
    (the certificate's ground rule stops at the far cap from the pose camera). Only valid px
    within `band` px of an invalid one are kept: the hidden hits land at the coverage edge (Inferno zs_v3: 0-11 px
    under the ridge top; deeper in, the Lipschitz sheet holds them). A px square has its vertices on the px corners
    (integer rest px, shared between neighbours: watertight; the outer boundary pushed FLOOR_FILL_EPS_PX out), so at the rest camera it contains exactly one px
    centre, its own: the fill rasterizes at rest only valid px, behind every state's surface (checked by the caller).
    -> {V (world), uv, tris, gridPx, report}. CPU: array ops on the frame (no raster)."""
    import cv2
    h, w = cover.shape
    m = B["margin"]
    tw, th = B["texSize"]
    t = math.tan(math.radians(sc.cam["fov"]) / 2)
    fl = T.Floor(sc.cam)
    # E px past the frame on each side, inside the backstop's texture margin: a pose ray whose floor hit projects just
    # outside the rest frame always counts as a ground hole (zs_v3 run 3: 5 px at loop_240, q 0.1-2.4 px left of the
    # frame, between Mesh_OuterL2 and the backstop). Nothing draws there at rest, so the fill stays hidden; the frame
    # edge's cover / zmax are replicated outward (the fill stands behind the edge's rest surface; the certificate
    # checks every pose)
    E = int(min(FLOOR_FILL_EXT_PX, m["left"], m["right"], m["top"], m["bottom"]))
    cover = np.pad(cover, E, mode="edge")
    zmax = np.pad(zmax, E, mode="edge")
    hp_, wp_ = cover.shape

    def floor_depth(u, v):                      # u, v: rest px coordinates of ray points (px centre = x + 0.5)
        xn = (u / w * 2 - 1) * t * w / h
        yn = (1 - v / h * 2) * t
        d = sc.cam["fwd"][None, None] + xn[..., None] * sc.cam["right"][None, None] + yn[..., None] * sc.cam["up"][None, None]
        nd = d @ fl.n
        big = np.abs(nd) > 1e-12
        s = np.where(big, fl.d / np.where(big, nd, 1.0), -1.0)      # forward depth (d's forward component is 1)
        return s, s * np.linalg.norm(d, axis=-1), d

    ys, xs = np.mgrid[0:hp_, 0:wp_]
    s, dist, _ = floor_depth(xs - E + 0.5, ys - E + 0.5)
    reach = max(float(np.linalg.norm(np.asarray(c["pos"], np.float64) - np.asarray(sc.cam["pos"], np.float64)))
                for c in cams.values())
    cap = far_cap + reach
    valid = cover & (s > 0) & (dist < cap) & (s > behind * zmax)
    dt = cv2.distanceTransform(valid.astype(np.uint8), cv2.DIST_L2, 3)
    keep = valid & (dt <= band)
    py, px = np.nonzero(keep)
    # px (x, y) -> corners (x, y), (x+1, y), (x, y+1), (x+1, y+1) of the (hp_+1) x (wp_+1) corner lattice (padded)
    cid = lambda cx, cy: cy * (wp_ + 1) + cx
    a_, b_, c_, e_ = cid(px, py), cid(px + 1, py), cid(px, py + 1), cid(px + 1, py + 1)
    tris = np.concatenate([np.stack([a_, c_, b_], -1), np.stack([b_, c_, e_], -1)]).astype(np.int64)
    used = np.unique(tris)
    remap = np.full((hp_ + 1) * (wp_ + 1), -1, np.int64)
    remap[used] = np.arange(len(used))
    uy, ux = (used // (wp_ + 1)).astype(np.float64) - E, (used % (wp_ + 1)).astype(np.float64) - E
    # outer boundary corners move FLOOR_FILL_EPS_PX outward: a pose ray whose floor hit lies on the fill's boundary edge
    # (zs_v3 run 2: q within 0.002 px of it, 1 px at loop_000 / loop_036 / loop_324) must not be lost to the raster's
    # tie rule. Direction: the sum of (corner - square centre) over the kept squares at the corner (0 inside, outward
    # normal on an edge, the diagonal at a convex or concave corner; 0 for two squares meeting at one corner only).
    # Still watertight (shared corners), and a square stays within eps of its px: it holds no other px centre at rest.
    off = np.zeros(((hp_ + 1) * (wp_ + 1), 2))
    for cc, (ox, oy) in ((a_, (-.5, -.5)), (b_, (.5, -.5)), (c_, (-.5, .5)), (e_, (.5, .5))):
        np.add.at(off, cc, (ox, oy))
    o_ = off[used]
    on = np.linalg.norm(o_, axis=-1)
    mv = on > 1e-9
    ux[mv] += FLOOR_FILL_EPS_PX * o_[mv, 0] / on[mv]
    uy[mv] += FLOOR_FILL_EPS_PX * o_[mv, 1] / on[mv]
    sc_, _, dc = floor_depth(ux[None], uy[None])
    sc_, dc = sc_[0], dc[0]
    if (sc_ <= 0).any():
        fail(f"floor fill: {int((sc_ <= 0).sum())} px corners have no floor point in front of the camera")
    V = np.asarray(sc.cam["pos"], np.float64)[None] + dc * sc_[:, None]
    uv = np.stack([(ux + m["left"]) / tw, 1 - (uy + m["top"]) / th], -1)
    gxy = np.stack([np.clip(ux, 0, w - 1), np.clip(uy, 0, h - 1)], -1).astype(np.int64)
    return {"V": V, "uv": uv, "tris": remap[tris], "gridPx": gxy, "px": np.stack([py - E, px - E], -1),
            "report": {"behind": behind, "bandPx": band, "camReachM": round(reach, 2), "capM": round(cap, 2), "validPx": int(valid.sum()),
                       "squaresPx": int(keep.sum()), "tris": int(len(tris)), "verts": int(len(used)),
                       "boundaryCornersMoved": int(mv.sum()), "epsPx": FLOOR_FILL_EPS_PX, "extPx": E,
                       "offFrameSquares": int(((px < E) | (px >= w + E) | (py < E) | (py >= h + E)).sum()),
                       "coverPx": int(cover[E:E + h, E:E + w].sum()),
                       "floorDepthM": [round(float(sc_.min()), 2), round(float(sc_.max()), 2)] if len(sc_) else []}}


def fill_ground_faces(V: np.ndarray, tris: np.ndarray, cam_pos: np.ndarray, cap: float, device: str) -> np.ndarray:
    """Per floor-fill face: True when one of its vertices lies within `cap` (the far cap) of a certified camera, i.e.
    the face is ground (the certificate's ground-hole rule) for some pose that may see it. The sky-side prune keeps
    such faces: it only sees the build's cams, and a fill face that is past the far cap for every build pose that
    meets it is still ground for a closer `final` pose (Inferno zs_v3 run 2: final loop_060 120 px, transition_011
    62 px of hidden ground on fill squares the prune had removed). V (n, 3) world, tris (f, 3), cam_pos (c, 3).
    cuda: torch cdist in chunks under the VRAM cap; cpu: the numpy reference (bit-equal booleans, parity in
    test_town_full3d_floor_fill.py). No fallback: cuda without a GPU fails."""
    V = np.asarray(V, np.float64); C = np.asarray(cam_pos, np.float64)
    if device == "cuda":
        import torch
        if not torch.cuda.is_available():
            fail("fill_ground_faces: device cuda and no CUDA device")
        tV = torch.as_tensor(V, device="cuda"); tC = torch.as_tensor(C, device="cuda")
        near = torch.empty(len(V), dtype=torch.bool, device="cuda")
        for i in range(0, len(V), FILL_GROUND_CHUNK):
            near[i:i + FILL_GROUND_CHUNK] = (torch.cdist(tV[i:i + FILL_GROUND_CHUNK], tC, compute_mode="donot_use_mm_for_euclid_dist").min(1).values < cap)
        near = near.cpu().numpy()
        del tV, tC
        torch.cuda.empty_cache()
    elif device == "cpu":
        near = np.zeros(len(V), bool)
        for i in range(0, len(V), FILL_GROUND_CHUNK):
            d = np.linalg.norm(V[i:i + FILL_GROUND_CHUNK, None] - C[None], axis=-1)
            near[i:i + FILL_GROUND_CHUNK] = d.min(1) < cap
    else:
        fail(f"fill_ground_faces: unknown device {device!r}")
    return near[np.asarray(tris, np.int64)].any(1)


def rest_colour(sc, T, TP, stage: Stage, keys: list, tex_cache: dict | None = None, want_fid: bool = False) -> tuple:
    """The rest frame's own albedo (sRGB, float) and normals of the given prefabs' bins, by perspective-correct
    barycentric sampling of the nearest face per px; (rgb, normal, fid-valid mask, z), + (fid, owner, names) with
    want_fid. tex_cache: albedo images by path, kept across calls (rest_paint renders every build state)."""
    import cv2
    from PIL import Image
    P, UV, F, owner, names, _, fmap = stage.arrays(keys)
    N = stage.normals(keys)
    z, fid = TP.zbuffer(sc.cam, P, F, sup=1)
    h, w = z.shape
    rgb = np.zeros((h, w, 3), np.float32)
    nrm = np.zeros((h, w, 3), np.float32)
    ok = fid >= 0
    ys, xs = np.nonzero(ok)
    f = F[fid[ok]]
    px, py, zc = T.project(sc.cam, P)
    sx, sy = px[f], py[f]                                   # (n, 3)
    qx, qy = xs + 0.5, ys + 0.5
    d = (sy[:, 1] - sy[:, 2]) * (sx[:, 0] - sx[:, 2]) + (sx[:, 2] - sx[:, 1]) * (sy[:, 0] - sy[:, 2])
    d = np.where(np.abs(d) < 1e-12, 1e-12, d)
    l0 = ((sy[:, 1] - sy[:, 2]) * (qx - sx[:, 2]) + (sx[:, 2] - sx[:, 1]) * (qy - sy[:, 2])) / d
    l1 = ((sy[:, 2] - sy[:, 0]) * (qx - sx[:, 2]) + (sx[:, 0] - sx[:, 2]) * (qy - sy[:, 2])) / d
    lam = np.clip(np.stack([l0, l1, 1 - l0 - l1], 1), 0, 1)
    lam = lam / np.maximum(zc[f], 1e-9)
    lam /= np.maximum(lam.sum(1, keepdims=True), 1e-12)
    uvq = np.einsum("nk,nkj->nj", lam, UV[f])
    nq = np.einsum("nk,nkj->nj", lam, N[f])
    nrm[ys, xs] = nq / np.maximum(np.linalg.norm(nq, axis=1, keepdims=True), 1e-9)
    own = owner[fid[ok]]
    for o in np.unique(own):
        b = stage.bins[int(fmap[np.flatnonzero(owner == o)[0], 0])]
        tp_ = b["path"].with_name(f"{b['name']}_albedo.png")
        img = tex_cache.get(tp_) if tex_cache is not None else None
        if img is None:
            img = np.asarray(Image.open(tp_).convert("RGB"), np.float32)
            if tex_cache is not None:
                tex_cache[tp_] = img
        th_, tw_ = img.shape[:2]
        s = own == o
        mx = (uvq[s, 0] * tw_ - 0.5).astype(np.float32)
        my = ((1 - uvq[s, 1]) * th_ - 0.5).astype(np.float32)
        k = -(-len(mx) // 4096) * 4096                  # remap's maps stay under SHRT_MAX per side
        mxp, myp = np.zeros(k, np.float32), np.zeros(k, np.float32)
        mxp[:len(mx)], myp[:len(my)] = mx, my
        col = cv2.remap(img, mxp.reshape(-1, 4096), myp.reshape(-1, 4096), cv2.INTER_LINEAR,
                        borderMode=cv2.BORDER_REPLICATE).reshape(-1, 3)[:len(mx)]
        rgb[ys[s], xs[s]] = col
    if want_fid:
        return rgb, nrm, ok, z, fid, owner, names
    return rgb, nrm, ok, z


def rest_paint_fx_masks(S, SC, rows: dict, lids) -> dict:
    """{lid: {"mask": HxW bool frame px, "spritePx", "effects": [...]}} for the layers whose smoke / flame effects
    have their emitter staged (REST_PAINT_FX_*); a layer with such an effect but no staged emitter is listed with
    mask None (its px count). Empty when the profile has no town_full3d_fx module."""
    import cv2
    from PIL import Image
    if getattr(SC.FP, "FX_MODULE", None) != "town_full3d_fx":
        return {}
    import town_full3d_fx as FX
    spec = FX.fx_layers()
    lays = SC.layers()
    meta = None
    out = {}
    k_dil = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * REST_PAINT_FX_DILATE_PX + 1,) * 2)
    for lid in sorted(set(lids) & set(spec)):
        effs = [(k, e) for k, e in enumerate(spec[lid]["effects"]) if e.get("kind") in REST_PAINT_FX_KINDS]
        if not effs:
            continue
        if meta is None:
            meta = FX.layer_meta(SC.anim_frames())
        L = lays[lid]
        F = FX.def_frames(meta, lid)
        dx, dy = FX.check_registration(meta, lid, L, F)
        ch = FX.changed_count(F)
        parts = {p["name"] for p in (rows.get(S.PREFIX + lid) or {}).get("particles") or []}
        sw, sh = SC.sprite(L).size
        m_spr = np.zeros((sh, sw), bool)
        rec = []
        for k, e in effs:
            pre = f"{REST_PAINT_FX_KINDS[e['kind']]}{k}_"
            emit = sorted(p for p in parts if p.startswith(pre))
            rec.append({"effect": k, "kind": e["kind"], "emitters": emit})
            if not emit:
                continue
            m = (ch > 0) & FX.rect_mask(ch.shape, e.get("rects"), e.get("exclude")) & FX.colour_mask(F, e.get("colour"))
            if e.get("colourNot"):
                m &= ~FX.colour_mask(F, e["colourNot"])
            ys, xs = np.nonzero(m)
            ys, xs = ys - dy, xs - dx
            keep = (ys >= 0) & (xs >= 0) & (ys < sh) & (xs < sw)
            m_spr[ys[keep], xs[keep]] = True
        if not any(r["emitters"] for r in rec):
            out[lid] = {"mask": None, "spritePx": 0, "effects": rec}
            continue
        big = np.asarray(Image.fromarray(m_spr.astype(np.uint8) * 255).resize(
            (round(sw * SC.SCALE), round(sh * SC.SCALE)), Image.NEAREST)) > 127
        frame = np.zeros((SC.H, SC.W), bool)
        x0, y0 = round(L["x"] * SC.SCALE), round(L["y"] * SC.SCALE)
        hh, ww = min(big.shape[0], SC.H - y0), min(big.shape[1], SC.W - x0)
        if hh > 0 and ww > 0:
            frame[y0:y0 + hh, x0:x0 + ww] = big[:hh, :ww]
        frame = cv2.dilate(frame.astype(np.uint8), k_dil).astype(bool)
        out[lid] = {"mask": frame, "spritePx": int((SC.sprite_frame(L)[..., 3] > 0).sum()), "effects": rec}
    return out


def fx_excluded_by_state(rp: dict) -> dict:
    """{state: {layer: px}} of the smoke / flame exclusion (every state, empty dicts included: the reader sees what
    was excluded where, and that nothing was elsewhere)."""
    return {st: {(f"{l} (override {x['share']:.0%} / {x['pxCap']} px)" if "shareOverride" in x else l): x["px"]
                 for l, x in v.get("fxExcluded", {}).items()} for st, v in rp["byState"].items()}


def apply_known_gaps(by: dict, known_gaps: list | None) -> None:
    """restPaint.knownGaps (approved by name: REST_PAINT_KNOWN_GAPS_APPROVED, checked in load_recipe) on rest_paint's
    byState: the named state passes only when every component of REST_PAINT_AREA px or more is listed, is at most the
    entry's maxPx, and is drawn mostly by the entry's layer. The entry is recorded in the state as "knownGap"."""
    for e in known_gaps or []:
        v = by.get(e["state"])
        if v is None:
            fail(f"rest paint: knownGaps names state {e['state']}, which the build states do not have")
        big = [c for c in v["components"] if c["px"] >= REST_PAINT_AREA]
        own = [max(c["drawnBy"].items(), key=lambda t: t[1])[0].split("/", 1)[0] if c["drawnBy"] else None
               for c in big]
        ok_gap = (len(big) == v["overAreaComponents"] and all(c["px"] <= e["maxPx"] for c in big)
                  and all(o == e["layer"] for o in own))
        v["knownGap"] = {**e, "applied": not v["pass"], "within": ok_gap}
        if not v["pass"] and ok_gap:
            v["pass"] = True


def rest_paint(S, SC, SM, T, TP, sc, rows: dict, layers_of: dict, share_override: dict | None = None,
               known_gaps: list | None = None) -> dict:
    """The rest-paint term (REST_PAINT_*): per build state, the staged bins' rest albedo (rest_colour) against the
    HoMM3 painting of that state (stronghold_full3d_scene.homm3_reference), inside the painted rect. The raster is
    the GPU zbuffer; the compare is numpy over one frame per state (no per-face work to port)."""
    import cv2
    keys_all = sorted({S.ENV_KEY} | {S.PREFIX + l for ls in layers_of.values() for l in ls})
    stage = Stage(S, SM, sc, rows, keys_all)
    cache, by = {}, {}
    rect = np.zeros((SC.H, SC.W), bool)
    rect[:SC.TH, :SC.TW] = True
    fxm = rest_paint_fx_masks(S, SC, rows, {l for ls in layers_of.values() for l in ls})
    for st, ls in layers_of.items():
        keys = [S.ENV_KEY] + [S.PREFIX + l for l in ls]
        rgb, _, ok, _, fid, owner, names = rest_colour(sc, T, TP, stage, keys, cache, want_fid=True)
        ref = np.asarray(S.homm3_reference(list(ls)), np.float32)
        sa, sr = rgb.sum(-1), ref.sum(-1)
        m = rect & ok & (sa > REST_PAINT_MIN_SUM) & (sr > REST_PAINT_MIN_SUM)
        excl, ex_by = np.zeros_like(m), {}
        for l in ls:
            if l not in fxm:
                continue
            if fxm[l]["mask"] is None:
                ex_by[l] = {"px": 0, "emitterMissing": [r["effect"] for r in fxm[l]["effects"]]}
                continue
            e_l = fxm[l]["mask"] & m
            ov = share_override.get(l) if share_override else None
            share = float(ov["share"]) if ov else REST_PAINT_FX_MAX_SHARE
            px_cap = int(ov["pxCap"]) if ov else REST_PAINT_FX_MAX_PX
            cap = min(px_cap, share * fxm[l]["spritePx"])
            if int(e_l.sum()) > cap:
                fail(f"rest paint: state {st}: the smoke / flame exclusion of {l} is {int(e_l.sum())} px, over "
                     f"{cap:.0f} (min of {px_cap} px and {share:.0%} of its "
                     f"{fxm[l]['spritePx']} sprite px)")
            ex_by[l] = {"px": int(e_l.sum()), "spritePx": fxm[l]["spritePx"], "share": share, "pxCap": px_cap,
                        **({"shareOverride": share_override[l]} if share_override and l in share_override else {}),
                        "effects": [r for r in fxm[l]["effects"] if r["emitters"]],
                        "emitterMissing": [r["effect"] for r in fxm[l]["effects"] if not r["emitters"]]}
            excl |= e_l
        m &= ~excl
        d = np.abs(rgb / np.maximum(sa, 1e-6)[..., None] - ref / np.maximum(sr, 1e-6)[..., None]).max(-1) * 100
        bad = cv2.morphologyEx((m & (d > REST_PAINT_CHROMA)).astype(np.uint8), cv2.MORPH_OPEN,
                               np.ones((3, 3), np.uint8))
        n, cc, stats, _ = cv2.connectedComponentsWithStats(bad, 8)
        comps = []
        for i in (np.argsort(-stats[1:, 4])[:5] + 1 if n > 1 else []):
            own = owner[fid[cc == i]]
            u, c = np.unique(own, return_counts=True)
            comps.append({"px": int(stats[i, 4]), "bbox": [int(x) for x in stats[i, :4]],
                          "drawnBy": {names[int(o)]: int(k) for o, k in sorted(zip(u, c), key=lambda t: -t[1])[:3]}})
        top = comps[0]["px"] if comps else 0
        over = int((stats[1:, 4] >= REST_PAINT_AREA).sum()) if n > 1 else 0
        by[st] = {"comparedPx": int(m.sum()), "differingPx": int(bad.sum()), "maxComponentPx": top,
                  "components": comps, "overAreaComponents": over,
                  "fxExcludedPx": int(excl.sum()), "fxExcluded": ex_by, "pass": top < REST_PAINT_AREA}
    apply_known_gaps(by, known_gaps)
    return {"schema": REST_PAINT_SCHEMA, "spec": {"chroma": REST_PAINT_CHROMA, "minSum": REST_PAINT_MIN_SUM,
                                                  "area": REST_PAINT_AREA, "open": "3x3",
                                                  "fxExclusion": {"kinds": sorted(REST_PAINT_FX_KINDS),
                                                                  "dilatePx": REST_PAINT_FX_DILATE_PX,
                                                                  "maxPx": REST_PAINT_FX_MAX_PX,
                                                                  "maxShare": REST_PAINT_FX_MAX_SHARE,
                                                                  "requires": "emitter staged in the layer prefab",
                                                                  "shareOverride": share_override or {}}},
            "byState": by, "maxComponentPx": max(v["maxComponentPx"] for v in by.values()),
            "failing": sorted(s for s, v in by.items() if not v["pass"]), "pass": all(v["pass"] for v in by.values()),
            "knownGaps": {s: v["knownGap"] for s, v in by.items() if "knownGap" in v}}


def sprite_frame_mask(SC, L: dict) -> np.ndarray:
    """A layer's opaque sprite px in the 1920x1080 frame (x SC.SCALE at its position): alpha > 128, minus the HoMM3
    magenta shadow leftovers."""
    import cv2
    spr = np.asarray(SC.sprite(L).convert("RGBA")).astype(np.int32)
    r_, g_, b_ = spr[..., 0], spr[..., 1], spr[..., 2]
    m = ((spr[..., 3] > 128) & ~((r_ > 120) & (b_ > 120) & (g_ < 0.62 * np.minimum(r_, b_)))).astype(np.uint8)
    out = np.zeros((SC.H, SC.W), np.uint8)
    x0, y0 = int(round(L["x"] * SC.SCALE)), int(round(L["y"] * SC.SCALE))
    w, h = int(round(m.shape[1] * SC.SCALE)), int(round(m.shape[0] * SC.SCALE))
    big = cv2.resize(m, (w, h), interpolation=cv2.INTER_NEAREST)
    xa, ya, xb, yb = max(0, x0), max(0, y0), min(SC.W, x0 + w), min(SC.H, y0 + h)
    if xb > xa and yb > ya:
        out[ya:yb, xa:xb] = big[ya - y0:yb - y0, xa - x0:xb - x0]
    return out.astype(bool)


def paint_order_cut(S, SC, T, TP, sc, stage: "Stage", rep: dict, layers_of: dict, tol: float = PAINT_ORDER_TOL) -> dict:
    """Painting order at rest over the build-state tree (recipe step "paintOrder", v2). HoMM3 draws the layers in
    positions.json order (z, then order: checked here, fail-closed), so a later layer covers an earlier one on its own
    sprite. A Meshy body is placed at its own contact depth and can stand in front of such a layer in 3D: Cove's Pub
    horde upgrade tbcvsa2p (z 0) over the hall's gable (z 1), the Kraken dwelling tbcvsor1 (z 0) over the mage guild
    tbcvgmg1 (z 1), each only in min_ states (rest paint 1326 / 458 px, Cove zs_v1 2026-10-02). cove_t2_stage's
    paintOrder cut is this rule over the profile's three states only, and neither layer is built in one of them.

    For every Meshy layer A and every layer B drawn after it in a state with A, the lit pieces of A (front, hull,
    residual, cloth; not fx, not decal) whose rest centroid lies on B's opaque sprite px and nearer the camera than B's
    own staged surface there (by tol), or where B stages no surface on its sprite, are dropped when every state that
    builds A also builds such a B for that face (no state then shows A's paint there; the B may differ per state, an
    upgrade chain). A face some state shows stays and is reported under "kept" (that state's painting shows A there);
    the rest-paint term measures the outcome either way. GPU raster (TP.zbuffer); the selection is per-face numpy
    over the centroids."""
    import town_full3d_building_depth as BD
    lays = SC.layers()
    order = list(lays)
    zo = [(lays[l].get("z", 0), lays[l].get("order", 0)) for l in order]
    if zo != sorted(zo):
        fail("paintOrder: positions.json is not in drawing order (z, then order)")
    states_with = {}
    for st, ls in layers_of.items():
        for l in ls:
            states_with.setdefault(l, set()).add(st)
    to_world = lambda v: sc.cpos + (v / sc.scale) @ sc.C.T
    depth = {}

    def b_depth(lb):
        if lb not in depth:
            bins = [b for b in stage.bins if b["key"] == S.PREFIX + lb and b["name"].startswith("Mesh_")
                    and not b["name"].startswith("Mesh_Decal_") and len(b["f"])]
            P, F, o = [], [], 0
            for b in bins:
                P.append(to_world(b["v"])); F.append(b["f"] + o); o += len(b["v"])
            z = TP.zbuffer(sc.cam, np.concatenate(P), np.concatenate(F), sup=1)[0] if o else \
                np.full((SC.H, SC.W), np.inf)
            depth[lb] = (z, sprite_frame_mask(SC, lays[lb]))
        return depth[lb]

    by = {}
    for a in sorted(states_with, key=order.index):
        row = (rep.get("buildings") or {}).get(a)
        if row is None or not BD.is_meshy(row):
            continue
        later = [lb for lb in order[order.index(a) + 1:] if lb in states_with and states_with[a] & states_with[lb]]
        ent = {"droppedTris": 0, "over": {}, "kept": {}}
        for bi, b in enumerate(stage.bins):
            if (b["key"] != S.PREFIX + a or not b["name"].startswith("Mesh_") or not len(b["f"])
                    or BD.piece_role(a, b["name"], True) in ("fx", "decal")):
                continue
            px, py, zc = T.project(sc.cam, to_world(b["v"]))
            cx = np.round(px[b["f"]].mean(1)).astype(np.int64)
            cy = np.round(py[b["f"]].mean(1)).astype(np.int64)
            zf = zc[b["f"]].mean(1)
            ok = (cx >= 0) & (cy >= 0) & (cx < SC.W) & (cy < SC.H)
            over = {}                       # later layer -> faces in front of its own surface on its sprite
            for lb in later:
                z, msk = b_depth(lb)
                on = np.zeros(len(b["f"]), bool)
                on[ok] = msk[cy[ok], cx[ok]]
                zb = np.full(len(b["f"]), np.inf)
                zb[ok] = z[cy[ok], cx[ok]]
                # B's own surface is behind the face, or B stages nothing there (the painting still shows B's paint
                # on its sprite: A's painted front there is A's sprite, which HoMM3 never shows; Cove tbcvsa2p over
                # the hall's gable, which the hall's staged pieces leave uncovered)
                sel = on & (zf < zb * (1 - tol))
                if sel.any():
                    over[lb] = sel
            # a face goes when every state that builds A also builds a later layer it stands in front of: then no
            # state's painting shows A there (an upgrade chain: tbcvsor1 over tbcvgmg1 in one state, tbcvgmg2 in another)
            drop = np.ones(len(b["f"]), bool) if over else np.zeros(len(b["f"]), bool)
            for st in states_with[a]:
                cov = np.zeros(len(b["f"]), bool)
                for lb, sel in over.items():
                    if lb in layers_of[st]:
                        cov |= sel
                drop &= cov
            for lb, sel in over.items():
                if (sel & drop).any():
                    ent["over"][lb] = ent["over"].get(lb, 0) + int((sel & drop).sum())
                if (sel & ~drop).any():
                    ent["kept"][lb] = ent["kept"].get(lb, 0) + int((sel & ~drop).sum())
            if drop.any():
                stage.drop(bi, np.flatnonzero(drop))
                ent["droppedTris"] += int(drop.sum())
        by[a] = ent
    return {"rule": "paint_order_cut", "tol": tol, "states": len(layers_of), "byLayer": by,
            "droppedTris": sum(v["droppedTris"] for v in by.values())}


def guarded_faces(F: np.ndarray, sd_vert: np.ndarray, guard_px: float = SEAM_GUARD_PX) -> np.ndarray:
    """seamAware: the faces with a vertex within guard_px of the body's rest silhouette (sd_vert: signed rest-frame px
    distance per vertex, > 0 outside the body, < 0 under it). Those faces carry the residual's seam with its body
    (seams_v1): the ones drawn at rest border it, and the hidden ones just under the silhouette fill the seam when a
    pose opens it."""
    near = np.abs(np.asarray(sd_vert, np.float64)) <= float(guard_px)
    return near[np.asarray(F, np.int64)].any(1) if len(F) else np.zeros(0, bool)


def plan_repairs(fails, rest_shown: dict, rules: set, guarded: dict | None = None, flap: set | None = None):
    """The repair of each failing face (bin, local face): drop when no state shows it at rest, else card. With
    guarded ({bin: bool per face}, seamAware) a guarded face takes neither rule: there is no further stage rule, so
    it is left as it is and reported. A face in flap (residual depth-step faces, rule flap) is torn the same way
    whether guarded or not: the flap built behind its near side backs the seam it carried. Returns
    ({(rule, bin): [faces]}, [skipped (bin, face)]); fails closed on a rule the recipe does not allow."""
    todo, skipped = {}, []
    for (bi, lf) in sorted(fails):
        if guarded is not None and bi in guarded and guarded[bi][lf] and (bi, lf) not in (flap or set()):
            skipped.append((bi, lf))
            continue
        rule = "drop" if rest_shown.get((bi, lf), 0) == 0 else "card"
        if rule not in rules:
            fail(f"repair: bin {bi} face {lf} needs '{rule}', which the recipe does not allow")
        todo.setdefault((rule, bi), []).append(lf)
    return todo, skipped


def seam_guard(sc, S, TP, T, stage: "Stage", rep: dict) -> dict:
    """{bin index: guarded face mask} for every residual (ray role) bin of a Meshy building layer: each layer's Meshy
    body is rendered alone at rest and the signed distance to its silhouette read at the residual's vertices."""
    from scipy import ndimage as ndi
    import town_full3d_building_depth as BD
    to_world = lambda v: sc.cpos + (v / sc.scale) @ sc.C.T
    out = {}
    for key in sorted({b["key"] for b in stage.bins if b["key"] != S.ENV_KEY}):
        lid = key[len(S.PREFIX):]
        row = (rep.get("buildings") or {}).get(lid)
        if row is None or not BD.is_meshy(row):
            continue
        idx = [(bi, BD.piece_role(lid, b["name"], True)) for bi, b in enumerate(stage.bins) if b["key"] == key]
        body = [bi for bi, role in idx if role == "meshy"]
        resid = [bi for bi, role in idx if role == "ray"]
        if not body or not resid:
            continue
        P, F, o = [], [], 0
        for bi in body:
            P.append(to_world(stage.bins[bi]["v"])); F.append(stage.bins[bi]["f"] + o); o += len(stage.bins[bi]["v"])
        z, _ = TP.zbuffer(sc.cam, np.concatenate(P), np.concatenate(F), sup=1)
        cov = np.isfinite(z)
        sd = np.where(cov, -ndi.distance_transform_edt(cov), ndi.distance_transform_edt(~cov))
        H, W = sd.shape
        for bi in resid:
            px, py, _ = T.project(sc.cam, to_world(stage.bins[bi]["v"]))
            xi = np.clip(np.floor(px).astype(np.int64), 0, W - 1)
            yi = np.clip(np.floor(py).astype(np.int64), 0, H - 1)
            out[bi] = guarded_faces(stage.bins[bi]["f"], sd[yi, xi])
    return out


def residual_bins(S, stage: "Stage", rep: dict) -> dict:
    """{residual (ray role) bin index of a Meshy layer: [that layer's lit body / residual / solid bin indices]}: the
    pieces rule flap tears, and the layer's own front that hides their flaps at rest (cloth and fx excluded: cloth
    moves off its rest front)."""
    import town_full3d_building_depth as BD
    out = {}
    for key in sorted({b["key"] for b in stage.bins if b["key"] != S.ENV_KEY}):
        lid = key[len(S.PREFIX):]
        row = (rep.get("buildings") or {}).get(lid)
        if row is None or not BD.is_meshy(row):
            continue
        roles = {bi: BD.piece_role(lid, b["name"], True) for bi, b in enumerate(stage.bins) if b["key"] == key}
        occ = [bi for bi, role in roles.items() if role in ("meshy", "ray", "solid")]
        for bi, role in roles.items():
            if role == "ray":
                out[bi] = occ
    return out


def support_drops_under(gs, rec: dict, drops: list, cap: int = 20) -> list:
    """The dropped ground faces (repair rule drop, recorded with their world triangles) whose horizontal footprint holds
    one of the piece's low points: the support the repair rounds removed from under it."""
    import town_full3d_ground_contact as GC
    low = gs._low(gs.stage.bins[rec["bin"]]["v"], rec["idx"], 1.0)
    q = low[:, [0, 2]]
    out = []
    for d in drops:
        t = np.asarray(d["tri"])[:, [0, 2]]
        v0, v1, v2 = t[1] - t[0], t[2] - t[0], q - t[0]
        den = v0[0] * v1[1] - v1[0] * v0[1]
        if abs(den) < 1e-12:
            continue
        u = (v2[:, 0] * v1[1] - v1[0] * v2[:, 1]) / den
        w = (v0[0] * v2[:, 1] - v2[:, 0] * v0[1]) / den
        if ((u >= -1e-9) & (w >= -1e-9) & (u + w <= 1 + 1e-9)).any():
            out.append({k: d[k] for k in ("round", "bin", "face")} | {"heightM": round(float(np.mean(d["tri"], 0) @ GC.UP), 3)})
            if len(out) >= cap:
                break
    return out


def reanchor_after_repair(sc, S, T, stage: "Stage", state_keys: dict, cycle: int, drops: list) -> dict | None:
    """v2, inside the repair / prune fixed point: the repair rounds may drop the ground faces an anchored piece stands
    on (Stronghold zs_v2 2026-10-02: Mesh_Houses piece 20 anchored at -0.30 m in step 2b, then 1.88 m over
    Mesh_Terrain after rule drop removed the Mesh_Back_Terrain faces under it). The contact gate on the repaired stage;
    when it fails, every floating piece is anchored again (GC.anchor, rest identity against the current rest frame)
    and the caller runs the rounds again on that geometry. None when the gate passes as it is. Fails closed when the
    re-anchored stage still fails, naming each piece, its gap and the dropped support under it."""
    import town_full3d_ground_contact as GC
    cat = json.loads((S.OUT / "catalog.json").read_text(encoding="utf-8"))
    cg = GC.contact_gate(GC.Scene(sc, stage, S.ENV_KEY, cat))
    if cg["pass"]:
        return None
    gs = GC.Scene(sc, stage, S.ENV_KEY, cat, state_keys=state_keys)
    before = GC.rest_identity(gs, None)
    moved = GC.anchor(gs, lambda faces=None: GC.rest_identity(gs, before, faces), T, strict=False)
    ch = GC.rest_identity(gs, before)
    gs.rasters.release()
    if any(ch.values()):
        fail(f"ground contact: re-anchoring after the repair rounds (cycle {cycle}) changed the rest frame "
             f"{({k: v for k, v in ch.items() if v})}")
    gs2 = GC.Scene(sc, stage, S.ENV_KEY, cat)
    cg2 = GC.contact_gate(gs2)
    rec = {"cycle": cycle,
           "floatingBefore": {k: v["worst"] for k, v in cg["byBin"].items() if v["floating"] or v["unsupported"]},
           "pieces": [{k: m.get(k) for k in ("name", "piece", "verts", "gapBeforeM", "how", "scale", "gapAfterM", "why")
                       if k in m} for m in moved],
           "pass": bool(cg2["pass"])}
    if not cg2["pass"]:
        diag = []
        for r_ in gs2.records():
            if np.isfinite(r_["gapM"]) and r_["gapM"] <= GC.CONTACT_GATE_M:
                continue
            e = cg2["byBin"][r_["name"]]
            if not (e["floating"] or e["unsupported"]) or (np.isfinite(r_["gapM"]) and
                                                           (round(r_["gapM"], 3), r_["piece"], r_["verts"]) not in
                                                           [tuple(w) for w in e["worst"]]):
                continue
            diag.append({"name": r_["name"], "piece": r_["piece"], "verts": r_["verts"],
                         "gapM": round(float(r_["gapM"]), 3) if np.isfinite(r_["gapM"]) else None,
                         "droppedSupport": support_drops_under(gs2, r_, drops)})
        gs2.rasters.release()
        fail(f"ground contact: the repair rounds left pieces without ground and re-anchoring (cycle {cycle}) does not "
             f"ground them: " + json.dumps({"pieces": diag, "reanchor": rec["pieces"],
                                             "gate": {k: v for k, v in cg2["byBin"].items()
                                                      if v["floating"] or v["unsupported"]}}))
    gs2.rasters.release()
    return rec


def build_flaps(sc, T, TP, stage: "Stage", lips: dict, occ_of: dict, cams: dict) -> dict:
    """Rule flap, after its faces are torn: for each residual bin, the flap behind the near side of its far-side lip
    vertices (town_full3d_step_flap), appended to the bin (same albedo, mirrored uv, the lip's normals)."""
    import town_full3d_step_flap as FL
    to_world = lambda v: sc.cpos + (v / sc.scale) @ sc.C.T
    out = {}
    for bi, far_v in sorted(lips.items()):
        b = stage.bins[bi]
        used = np.zeros(len(b["v"]), bool)
        used[b["f"].ravel()] = True
        far_v = np.asarray(sorted(far_v), np.int64)
        far_v = far_v[used[far_v]]
        if not len(far_v):
            continue
        Ps, Fs, o = [], [], 0
        for bj in occ_of[bi]:
            bb = stage.bins[bj]
            Ps.append(to_world(bb["v"])); Fs.append(bb["f"] + o); o += len(bb["v"])
        z_front, _ = TP.zbuffer(sc.cam, np.concatenate(Ps), np.concatenate(Fs), sup=1)
        Pw = to_world(b["v"])
        px, py, zc = T.project(sc.cam, Pw)

        def opening(gx, gy, zn, zf):
            pn, pf = FL.px_world(sc.cam, gx, gy, zn), FL.px_world(sc.cam, gx, gy, zf)
            m = np.zeros(len(gx))
            for cam in cams.values():
                ax, ay, _ = T.project(cam, pn)
                bx, by, _ = T.project(cam, pf)
                m = np.maximum(m, np.hypot(ax - bx, ay - by))
            return m
        g = FL.flap_grid(px[far_v], py[far_v], zc[far_v], far_v, z_front, opening, (z_front.shape[1], z_front.shape[0]))
        if g is None:
            continue
        # per chart (town_full3d_step_flap.uv_affine_charts): each flap vertex takes the rest px -> uv map of the
        # chart its nearest lip vertex belongs to (Cove / Necropolis zs_v1 2026-10-02: residuals that pack several
        # crops in one atlas, 256 / 713 texels off one map)
        mi = b["vMap"][g["lipVertex"]]
        if (mi < 0).any():
            fail(f"flap: {b['key']}/{b['name']}: {int((mi < 0).sum())} flap vertices lie off every chart with a rest "
                 f"px -> uv map")
        A_ = np.c_[g["mx"], g["my"], np.ones(len(g["mx"]))]
        uv = np.clip(np.einsum("nk,nkj->nj", A_, b["uvMaps"][mi]), 0.0, 1.0)
        tris = FL.orient_like(g["tris"], g["x"], g["y"], b["f"], px, py)
        off = len(b["v"])
        b["v"] = np.concatenate([b["v"], sc.local(FL.px_world(sc.cam, g["x"], g["y"], g["z"]))])
        b["n"] = np.concatenate([b["n"], b["n"][g["lipVertex"]]])
        b["uv"] = np.concatenate([b["uv"], uv])
        b["vMap"] = np.concatenate([b["vMap"], mi])
        b["f"] = np.concatenate([b["f"], tris + off])
        sid = int(np.bincount(b["sid"]).argmax()) if len(b["sid"]) else 0
        b["sid"] = np.concatenate([b["sid"], np.full(len(tris), sid, np.int32)])
        b["dirty"] = True
        out[f"{b['key'][len(stage.S.PREFIX):]}/{b['name']}"] = {"lipVerts": int(len(far_v)), "flapPx": g["flapPx"],
                                                                "flapTris": int(len(tris)),
                                                                "openingMaxPx": round(g["openingMaxPx"], 1)}
    return out


def sky_side_hits(sc, T, TP, ZS, stage: "Stage", state_keys: dict, cams: dict, bs_bi: int, m: dict):
    """Every pose ray of every state that meets the backstop: ({backstop tris a sky ray sees}, {... a ground ray
    sees}, [(texel x, texel y, backstop tri, ground ray)]). A ground ray meets the painted floor plane inside the far
    cap (the certificate's ground-hole rule)."""
    fl0 = T.Floor(sc.cam)
    hits, sky_t, ground_t = [], set(), set()
    name = f"environment/{stage.bins[bs_bi]['name']}"
    for s, ks in state_keys.items():
        P, UV, F, owner, names, texs, fmap = stage.arrays(ks)
        nb0 = names.index(name)
        for cam in cams.values():
            zq, fq = TP.zbuffer(cam, P, F, sup=1)
            hit = (fq >= 0) & (owner[np.maximum(fq, 0)] == nb0)
            if not hit.any():
                continue
            wp = ZS.world_points(cam, np.where(hit, zq, np.nan))[hit]
            dw = wp - cam["pos"][None]
            dw /= np.maximum(np.linalg.norm(dw, axis=1, keepdims=True), 1e-12)
            nd = dw @ fl0.n
            with np.errstate(divide="ignore", invalid="ignore"):
                t_hit = (fl0.d - float(fl0.n @ (cam["pos"] - sc.cam["pos"]))) / nd
            gr = (t_hit > 0) & (t_hit < T.FAR_CAP_M)
            tri = fmap[fq[hit], 1]
            qx, qy, _ = T.project(sc.cam, wp)
            hits.append((np.floor(qx + m["left"]).astype(np.int64), np.floor(qy + m["top"]).astype(np.int64), tri, gr))
            sky_t.update(np.unique(tri[~gr]).tolist())
            ground_t.update(np.unique(tri[gr]).tolist())
    return sky_t, ground_t, hits


def ground_ray_px(sc, T, cam: dict, device: str) -> np.ndarray:
    """(H, W) bool: the pose px whose ray meets the painted floor plane (T.Floor of the rest camera) inside the far cap
    (the certificate's ground-hole rule, sky_side_hits' `gr`). It depends on the ray direction only, so it is one mask
    per pose for every geometry. cuda: torch float64; cpu: the numpy reference (parity in
    test_town_full3d_prune_ground.py). No fallback: cuda without a GPU fails."""
    import math
    from stronghold_full3d_common import W, H
    fl0 = T.Floor(sc.cam)
    t = math.tan(math.radians(cam["fov"]) / 2)
    off = float(fl0.d - float(fl0.n @ (cam["pos"] - sc.cam["pos"])))
    if device == "cuda":
        import torch
        if not torch.cuda.is_available():
            fail("ground_ray_px: device cuda and no CUDA device")
        dv = "cuda"
        ys, xs = torch.meshgrid(torch.arange(H, device=dv, dtype=torch.float64),
                                torch.arange(W, device=dv, dtype=torch.float64), indexing="ij")
        v = lambda a: torch.as_tensor(np.asarray(a, np.float64), device=dv)
        xn = ((xs + 0.5) / W * 2 - 1) * t * W / H
        yn = (1 - (ys + 0.5) / H * 2) * t
        d = v(cam["fwd"])[None, None] + xn[..., None] * v(cam["right"])[None, None] + yn[..., None] * v(cam["up"])[None, None]
        d = d / torch.clamp(torch.linalg.norm(d, dim=-1, keepdim=True), min=1e-12)
        nd = d @ v(fl0.n)
        th = off / nd
        out = ((th > 0) & (th < T.FAR_CAP_M) & torch.isfinite(th)).cpu().numpy()
        del ys, xs, xn, yn, d, nd, th
        return out
    if device != "cpu":
        fail(f"ground_ray_px: unknown device {device!r}")
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float64)
    xn = ((xs + 0.5) / W * 2 - 1) * t * W / H
    yn = (1 - (ys + 0.5) / H * 2) * t
    d = (np.asarray(cam["fwd"])[None, None] + xn[..., None] * np.asarray(cam["right"])[None, None]
         + yn[..., None] * np.asarray(cam["up"])[None, None])
    d = d / np.maximum(np.linalg.norm(d, axis=-1, keepdims=True), 1e-12)
    nd = d @ np.asarray(fl0.n, np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        th = off / nd
    return (th > 0) & (th < T.FAR_CAP_M) & np.isfinite(th)


def final_ground_tris(stage: "Stage", state_keys: dict, cams: dict, masks: dict, bs_bi: int) -> set:
    """Backstop triangles a ground ray (ground_ray_px) of the given poses meets, over every state: the poses the build
    does not certify but `final` does (reachable_cams_full). One raster context per call (town_gpu_kernels.Raster,
    byte-identical to TP.zbuffer), geometry uploaded once per state."""
    import town_gpu_kernels as GK
    out = set()
    if not cams:
        return out
    rs = GK.Raster()
    try:
        for s, ks in state_keys.items():
            P, UV, F, owner, names, texs, fmap = stage.arrays(ks)
            nb0 = names.index(f"environment/{stage.bins[bs_bi]['name']}")
            rs.load(P, F)
            for k, cam in cams.items():
                _, fq = rs.render(cam)
                sel = (fq >= 0) & masks[k]
                sel[sel] = owner[fq[sel]] == nb0
                if sel.any():
                    out.update(np.unique(fmap[fq[sel], 1]).tolist())
    finally:
        rs.release()
    return out


def cert_cams_of(sc, ZS, r: dict) -> dict:
    """The build's certified poses: the loop's samples plus certificate.extraPoses, or `final`'s own pose set
    (reachable_cams_full(sc, FINAL_LOOP)) when extraPoses is "final"."""
    xp = r["certificate"].get("extraPoses", ())
    if xp == EXTRA_POSES_FINAL:
        return ZS.reachable_cams_full(sc, FINAL_LOOP)
    return ZS.reachable_cams(sc, int(r["certificate"].get("loop", 12)), xp)


def finish(path: Path) -> int:
    import cv2
    from PIL import Image
    sys.path.insert(0, str(HERE))
    import stronghold_full3d_common as SC
    import stronghold_full3d_scene as S
    import stronghold_full3d_terrain as T
    import town_full3d_ldi as L
    import town_full3d_t2_paint as TP
    import town_full3d_zero_streak as ZS
    import town_t2_streak_map as SM
    r = load_recipe(path)
    if S.CANDIDATE != r["candidate"]:
        fail(f"_finish runs inside the candidate {r['candidate']} (TOWN_FULL3D_CANDIDATE={S.CANDIDATE})")
    t0 = time.time()
    sc = S.Scene()
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    if any(b["name"] == BACKSTOP_BIN for b in rows[S.ENV_KEY]["bins"]):
        fail(f"{S.ENV_KEY} already stages {BACKSTOP_BIN} (re-seed the candidate)")
    v2 = r["schema"] == SCHEMA_V2
    layers_of = build_states(SC, r)
    states = list(layers_of)
    state_keys = {s: [S.ENV_KEY] + [S.PREFIX + l for l in layers_of[s]] for s in states}
    missing = sorted({k for ks in state_keys.values() for k in ks if k not in rows})
    if missing:
        fail(f"build states name prefabs the candidate does not stage: {missing}")
    all_keys = sorted({k for ks in state_keys.values() for k in ks})
    cams = cert_cams_of(sc, ZS, r)
    # the certified pose set: the build's cams and `final`'s full sweep. Every ground-bearing keep of the sky-side
    # prune reads it (the fill's far-cap reach, fill_ground_faces, and the backstop's ground rays, final_ground_tris)
    cert_cams = {**cams, **ZS.reachable_cams_full(sc, FINAL_LOOP)}
    stage = Stage(S, SM, sc, rows, all_keys)
    # ---- 2a. periphery settle (v2, opt-in): no periphery sheet in front of the staged frame surface at rest; every
    # v2 recipe measures the intrusion (reported in the result), the step fixes the listed pieces
    per_settle = None
    if v2:
        outer = sorted({b["name"] for b in stage.bins if b["key"] == S.ENV_KEY and b["name"].startswith(PERIPHERY_PREFIX)})
        fixed = None
        if "peripherySettle" in r:
            fixed = periphery_settle(sc, T, TP, stage, S.ENV_KEY, r["peripherySettle"]["pieces"])
            fixed["why"] = r["peripherySettle"]["why"]
        per_settle = {"settle": fixed,
                      "measured": periphery_settle(sc, T, TP, stage, S.ENV_KEY, outer, apply=False)["rounds"][0]}
        print("PERIPHERY", json.dumps({"settle": None if fixed is None else
                                       {k: fixed[k] for k in ("intrusionPxBefore", "intrusionPxAfter", "verticesMoved")},
                                       "intrusionPxNow": per_settle["measured"]["intrusionPx"],
                                       "byPiece": per_settle["measured"]["byPiece"]}), flush=True)
    # ---- 2a'. rest ownership (v2, opt-in "restOwner"): the listed layers drawn at rest only where the painting shows
    # them; before ground contact, so anchoring and every later term see the settled bodies
    rest_own = None
    if v2 and "restOwner" in r:
        rest_own = rest_owner(S, SC, T, TP, sc, stage, layers_of, r["restOwner"]["layers"])
        rest_own["why"] = r["restOwner"]["why"]
        print("REST OWNER DONE", json.dumps({k: rest_own[k] for k in ("stop", "misownedPxBefore", "misownedPxAfter",
                                                                     "noOwnerSurfacePxAfter", "facesDropped",
                                                                     "verticesPushed")}), flush=True)
    # ---- 2a2. painting order (opt-in "paintOrder", v2): a Meshy body in front of a layer HoMM3 draws over it
    paint_order = None
    if "paintOrder" in r:
        rep_po = json.loads((S.WORK / "stage_report.json").read_text(encoding="utf-8"))
        paint_order = paint_order_cut(S, SC, T, TP, sc, stage, rep_po, layers_of)
        print("PAINT ORDER", json.dumps({k: {"dropped": v["droppedTris"], "kept": v["kept"]}
                                         for k, v in paint_order["byLayer"].items()
                                         if v["droppedTris"] or v["kept"]}), flush=True)
    # ---- 2b. ground contact (v2): every floating environment piece grounded, the rest frame identical in every state
    anchored = None
    if v2:
        import town_full3d_ground_contact as GC
        cat = json.loads((S.OUT / "catalog.json").read_text(encoding="utf-8"))
        removed = []
        if r.get("groundContact", {}).get("removeHidden"):
            # before the Scene: its pieces and rasters are taken from the stage as it then is
            cams_rh = {**ZS.reachable_cams_full(sc, 48), **cams}          # every sweep sample, final's poses, the recipe's
            removed = GC.remove_hidden(stage, sc, S.ENV_KEY, cat, cams_rh, r["groundContact"]["removeHidden"])
            print("REMOVED HIDDEN", json.dumps(removed), flush=True)
        gs = GC.Scene(sc, stage, S.ENV_KEY, cat, state_keys=state_keys)
        before = GC.rest_identity(gs, None)
        before0 = dict(before)                  # extensionDrop rebases `before` in place
        drop = {"before": before, "rect": (SC.TH, SC.TW)} \
            if r.get("groundContact", {}).get("extensionDrop", False) else None
        anchored = GC.anchor(gs, lambda faces=None: GC.rest_identity(gs, before, faces), T, drop=drop)
        ch = GC.rest_identity(gs, before)
        now = GC.rest_identity(gs, None)
        ch_rect = {k: int((now[k][:SC.TH, :SC.TW] != before0[k][:SC.TH, :SC.TW]).sum()) for k in now}
        gs.rasters.release()
        if any(ch.values()) or any(ch_rect.values()):
            fail(f"ground contact: anchoring changed the rest frame {({k: v for k, v in ch.items() if v})} "
                 f"(painted rect {({k: v for k, v in ch_rect.items() if v})})")
        cg = GC.contact_gate(GC.Scene(sc, stage, S.ENV_KEY, cat))
        print("ANCHOR", json.dumps({"moved": len(anchored), "pass": cg["pass"]}), flush=True)
        if not cg["pass"]:
            fail("ground contact: pieces still float or have no ground under them after anchoring "
                 + json.dumps({k: v for k, v in cg["byBin"].items() if v["floating"] or v["unsupported"]}))
    # ---- 3. backstop geometry: behind the environment alone (hidden at rest in every state)
    bs = r["backstop"]
    rgb_env, nrm_env, env_ok, z_env = rest_colour(sc, T, TP, stage, [S.ENV_KEY])
    B = lipschitz_backstop(sc, TP, z_env, cams, float(bs.get("K", 2.0)), int(bs.get("stepPx", 4)), float(T.FAR_CAP_M))
    env_row = next(b for b in rows[S.ENV_KEY]["bins"] if b["name"] == r["ldi"]["pieces"][0])
    row = dict(env_row)
    row.update({"name": BACKSTOP_BIN, "mesh": env_row["mesh"].replace(f"/{env_row['name']}.bytes", f"/{BACKSTOP_BIN}.bytes"),
                "texture": env_row["texture"].replace(f"/{env_row['name']}_albedo.png", f"/{BACKSTOP_BIN}_albedo.png")})
    tw, th = B["texSize"]
    FF = None
    if bs.get("groundFloor"):
        cover, zmax = rest_cover(sc, TP, stage, state_keys, ZS.DEVICE)
        # reach over the build's cams and `final`'s full sweep: the fill must hold for every certified pose
        FF = floor_fill(sc, T, B, cover, zmax, float(T.FAR_CAP_M), cert_cams)
        print("FLOOR FILL", json.dumps(FF["report"]), flush=True)
        if not FF["report"]["tris"]:
            fail("floor fill: backstop.groundFloor is set and no grid cell qualifies")
        nb0 = len(B["V"])
        B["report"]["floorFill"] = FF["report"]
        B["fillTris"] = (len(B["tris"]), len(B["tris"]) + len(FF["tris"]))
        B["V"] = np.concatenate([B["V"], FF["V"]])
        B["uv"] = np.concatenate([B["uv"], FF["uv"]])
        B["tris"] = np.concatenate([B["tris"], FF["tris"] + nb0])
        B["gridPx"] = np.concatenate([B["gridPx"], FF["gridPx"]])
        B["fillVerts"] = (nb0, len(B["V"]))
        # fill faces that are ground for some certified pose: the sky-side prune keeps them (fill_ground_faces)
        fg = fill_ground_faces(FF["V"], FF["tris"], np.array([c["pos"] for c in cert_cams.values()]),
                               float(T.FAR_CAP_M), ZS.DEVICE)
        prune_keep = np.zeros(len(B["tris"]), bool)
        prune_keep[B["fillTris"][0]:] = fg
        FF["report"]["groundFacesKept"] = int(fg.sum())
        print("FLOOR FILL GROUND", json.dumps({"faces": int(len(fg)), "groundForSomePose": int(fg.sum())}), flush=True)
    else:
        prune_keep = np.zeros(len(B["tris"]), bool)
    Vb_local = sc.local(B["V"])
    bpath = S.STAGE / S.ENV_KEY / f"{BACKSTOP_BIN}.bytes"
    stage.bins.append({"key": S.ENV_KEY, "name": BACKSTOP_BIN, "path": bpath, "v": Vb_local,
                       "n": np.zeros_like(Vb_local), "uv": B["uv"], "f": B["tris"].astype(np.int64),
                       "sid": np.zeros(len(B["tris"]), np.int32), "nsub": 1, "tex": (tw, th), "dirty": True})
    bs_bi = len(stage.bins) - 1
    # ---- 3b. sprite ground decals (opt-in "decal"): the sprite paint a building lays on the environment, on the
    # environment's own rest surface, in the building's prefab. Before the rounds, so they certify the new faces
    decal = None
    if "decal" in r:
        import town_full3d_sprite_decal as DC
        # the smoke / flame px the scene draws as Fx (rest-paint's own exclusion masks) are never ground paint
        fxm = rest_paint_fx_masks(S, SC, rows, {l for ls in layers_of.values() for l in ls})
        pl = DC.plan(S, SC, T, TP, sc, stage, rows, layers_of, (rgb_env, nrm_env, env_ok, z_env), REST_PAINT_CHROMA,
                     REST_PAINT_MIN_SUM, fx_masks={l: v["mask"] for l, v in fxm.items() if v["mask"] is not None},
                     layer_depth="layerDepth" in r["decal"])
        decal = pl["report"] | {"bins": DC.apply(S, stage, rows, pl)}
        print("DECAL", json.dumps({k: v.get("decalPx", 0) for k, v in decal["byLayer"].items() if v.get("decalPx")}),
              flush=True)
    # ---- 4. repair rounds over every state
    rules = set(r["repair"].get("rules", []))
    rest_shown = {}
    for s, ks in state_keys.items():           # faces any state shows at rest are never dropped
        P, UV, F, owner, names, texs, fmap = stage.arrays(ks)
        _, fid = TP.zbuffer(sc.cam, P, F, sup=1)
        cnt = np.bincount(fid[fid >= 0], minlength=len(F))
        for (bi, lf), c in zip(fmap.tolist(), cnt.tolist()):
            if c:
                rest_shown[(bi, lf)] = rest_shown.get((bi, lf), 0) + c
    if FF is not None:                          # the floor fill is hidden at rest in every state, or the build fails
        lo, hi = B["fillTris"]
        shown_fill = {lf: c for (bi, lf), c in rest_shown.items() if bi == bs_bi and lo <= lf < hi}
        if shown_fill:
            fail(f"floor fill: {len(shown_fill)} fill faces draw {sum(shown_fill.values())} px at rest "
                 f"(states summed); FLOOR_FILL_BEHIND {FLOOR_FILL_BEHIND} does not hide them")
    hist, dropped, carded, skipped, planar_n = [], 0, 0, 0, 0
    guarded = None
    if r["repair"].get("seamAware"):
        rep0 = json.loads((S.WORK / "stage_report.json").read_text(encoding="utf-8"))
        guarded = seam_guard(sc, S, TP, T, stage, rep0)
        print("SEAM GUARD", json.dumps({f"{stage.bins[bi]['key'][len(S.PREFIX):]}/{stage.bins[bi]['name']}":
                                        int(m.sum()) for bi, m in guarded.items()}), flush=True)
    import town_full3d_step_flap as FL
    rep_st = json.loads((S.WORK / "stage_report.json").read_text(encoding="utf-8"))
    flap_of = residual_bins(S, stage, rep_st) if "flap" in rules else {}
    flap_charts_off = {}
    for bi in flap_of:                          # the residual's own rest px -> uv maps, before any flap is appended
        b = stage.bins[bi]
        bx, by, _ = T.project(sc.cam, sc.cpos + (b["v"] / sc.scale) @ sc.C.T)
        shown = np.asarray(sorted({lf for (b2, lf) in rest_shown if b2 == bi}), np.int64)
        ch, maps, off = FL.uv_affine_charts(bx, by, b["f"], b["uv"], shown, b["tex"]) if len(shown) else \
            (np.zeros(len(b["f"]), np.int64), {}, {})
        if not maps:
            fail(f"flap: {b['key']}/{b['name']}: no uv chart is an affine map of rest px (texels off {off})")
        keys = sorted(maps)
        b["uvMaps"] = np.stack([maps[c] for c in keys])
        vmap = np.full(len(b["v"]), -1, np.int64)
        lut = {c: i for i, c in enumerate(keys)}
        fm = np.asarray([lut.get(int(c), -1) for c in ch], np.int64)
        for k in range(3):
            vmap[b["f"][:, k]] = np.maximum(vmap[b["f"][:, k]], fm)
        # a vertex of a chart without a map (too few rest-shown vertices, or a back-fill chart) takes the map of the
        # mapped vertex nearest to it in rest px: the paint around where it stands, as rule planar does
        miss = np.flatnonzero(vmap < 0)
        if len(miss):
            from scipy.spatial import cKDTree
            have = np.flatnonzero(vmap >= 0)
            _, nn = cKDTree(np.c_[bx[have], by[have]]).query(np.c_[bx[miss], by[miss]])
            vmap[miss] = vmap[have[nn]]
        b["vMap"] = vmap
        if off:
            flap_charts_off[f"{b['key']}/{b['name']}"] = off
    flap_rep, flap_faces = [], 0
    work = S.WORK / "zero_streak_recipe"
    work.mkdir(parents=True, exist_ok=True)
    # ---- 4 + 5a. repair rounds and the sky-side prune, to a fixed point. The prune reads the repaired geometry (a
    # drop shows the backstop to new rays), and a pruned backstop triangle shows what was behind it, which no round has
    # certified (Rampart zs_v1: periphery faces behind the pruned sheet). So: rounds until clean, then the prune; when
    # it removes anything, rounds again on the pruned geometry; it ends when the prune of a certified geometry removes
    # nothing. Nothing after this loop may change what the gate measures (Stage.require_certified).
    n_rounds = int(r["repair"].get("rounds", 8))
    rnd, certified, prune_hist = -1, None, []
    final_only = {k: c for k, c in cert_cams.items() if k not in cams}   # certified poses the build's rounds do not see
    final_masks = None                                                 # their ground_ray_px, made once on first use
    reanchor_hist, support_drops, n_prune = [], [], 0      # v2: re-anchors inside the fixed point
    import town_full3d_ground_contact as GCm
    env_ground = {bi for bi, b in enumerate(stage.bins) if v2 and b["key"] == S.ENV_KEY
                  and GCm.classify(b["name"]) == "ground"}
    m = B["margin"]
    seam_weld_on, weld_hist = bool(r["repair"].get("seamWeld")), []
    last_cycle = PRUNE_CYCLES + REANCHOR_CYCLES + (SEAM_WELD_CYCLES if seam_weld_on else 0)
    for cycle in range(last_cycle + 1):   # a re-anchor or seam-weld cycle runs no prune
        for _k in range(n_rounds + 1):
            rnd += 1
            fails, ufails, summ = {}, {}, {}
            for s, ks in state_keys.items():
                P, UV, F, owner, names, texs, fmap = stage.arrays(ks)
                hits: dict = {}
                uhits: dict = {}
                rep = ZS.certify(sc, P, UV, F, owner, names, texs, cams, out=None, faces_out=hits,
                                 sky=ZS.load_sky(sc, rows, ks),
                                 unseen_out=uhits if v2 else None)
                summ[s] = rep["summary"]
                for f, n in hits.items():
                    key = tuple(fmap[f].tolist())
                    fails[key] = fails.get(key, 0) + n
                for f, n in uhits.items():
                    key = tuple(fmap[f].tolist())
                    ufails[key] = ufails.get(key, 0) + n
            ufails = {k: v for k, v in ufails.items() if k not in fails}   # a face both ways takes the stage rules
            hist.append({"round": rnd, "cycle": cycle, "summaryByState": summ, "facesFailing": len(fails),
                         "unseenFacesFailing": len(ufails)})
            print("ROUND", rnd, json.dumps({s: {k: v[k] for k in ("maxVisibleBehindPx", "maxUnseenFacePx",
                                                                  "groundHoleGrowthPx", "pass")}
                                             for s, v in summ.items() if not v["pass"] or v["groundHoleGrowthPx"]
                                             or (v2 and v["maxUnseenFacePx"])}), "failing faces", len(fails), "unseen", len(ufails), flush=True)
            if not fails and not ufails:
                break
            if len(fails) <= 64:                    # the last few faces by bin (diagnostic: which pieces stall)
                byb: dict = {}
                for (bi, lf), n in fails.items():
                    nm = f"{stage.bins[bi]['key'][len(S.PREFIX):] if stage.bins[bi]['key'] != S.ENV_KEY else 'env'}/{stage.bins[bi]['name']}"
                    byb.setdefault(nm, []).append([int(lf), int(n)])
                print("FAILING", json.dumps(byb), flush=True)
            if _k == n_rounds:
                fail(f"repair: {len(fails)} faces still fail after {n_rounds} rounds (cycle {cycle})")
            if any(bi == bs_bi for bi, _ in fails):
                fail("repair: the backstop itself streaks (its bound is broken)")
            flap, lips = set(), {}
            for bi in sorted({bi for bi, _ in fails if bi in flap_of}):
                b = stage.bins[bi]
                lfs = np.asarray(sorted(lf for b2, lf in fails if b2 == bi), np.int64)
                _, _, zc = T.project(sc.cam, sc.cpos + (b["v"] / sc.scale) @ sc.C.T)
                st = lfs[FL.step_faces(zc[b["f"][lfs]])]
                if len(st):
                    flap.update((bi, int(lf)) for lf in st)
                    lips[bi] = set(FL.far_vertices(b["f"], zc, st).tolist())
            todo, skip = plan_repairs(fails, rest_shown, rules, guarded, flap)
            planar_held = {}
            if ufails:                              # the unseen-face term (v2): rule planar, fail-closed
                if any(bi == bs_bi for bi, _ in ufails):
                    fail("repair: the backstop itself draws unseen-face stretch")
                if "planar" not in rules:
                    fail(f"repair: {len(ufails)} unseen faces stretch and the recipe does not allow rule planar")
                # a face that still stretches with planar uv: when no state shows it at rest and the recipe allows
                # drop, it takes rule drop (the premise of a dropped behind-streak face: the rest frame keeps every px,
                # the backstop shows where it opened, the next round certifies that). Fortress zs_v2 2026-10-02:
                # Mesh_Body_tbfrdw_3 faces 1805-1812, rest area 0 px (edge-on: one rest px, depth 75 -> 337 m, 2-20 m2),
                # s1 8-52 px per texel at loop_108 / sweep_left even with planar uv: a rest-ray sliver, which no uv can
                # lay without stretch. A face shown at rest has no further stage rule; like a card that fails again
                # (below) it is held out of this round, and the build fails closed when only held faces are left
                for (bi, lf) in sorted(ufails):
                    if lf in (stage.bins[bi].get("planar") or set()):
                        if "drop" in rules and not rest_shown.get((bi, lf), 0):
                            todo.setdefault(("drop", bi), []).append(lf)
                            hist[-1].setdefault("planarRefailDropped", {}).setdefault(
                                f"{stage.bins[bi]['key']}/{stage.bins[bi]['name']}", []).append(int(lf))
                        else:
                            planar_held.setdefault(bi, []).append(lf)
                        continue
                    todo.setdefault(("planar", bi), []).append(lf)
                if planar_held:
                    hist[-1]["planarRefailHeld"] = {f"{stage.bins[bi]['key']}/{stage.bins[bi]['name']}": v
                                                    for bi, v in planar_held.items()}
            # a face that already is a card has no further stage rule. It is held out of this round rather than failed
            # at once: it may be a few px of a component other faces still streak in (Stronghold zs_v2, 2026-10-02: a
            # 2 px card of a 230-face round). The build fails closed when only such cards (or seam-guarded faces) are
            # left, and the round cap still holds: the certificate itself is unchanged
            refail = {}
            for (rule, bi) in list(todo):
                held = stage.bins[bi].get("carded")
                if rule != "card" or held is None or not set(todo[(rule, bi)]) & held:
                    continue
                refail[bi] = sorted(set(todo[(rule, bi)]) & held)
                rest = [lf for lf in todo[(rule, bi)] if lf not in held]
                if rest:
                    todo[(rule, bi)] = rest
                else:
                    del todo[(rule, bi)]
            if refail:
                hist[-1]["cardRefailHeld"] = {f"{stage.bins[bi]['key']}/{stage.bins[bi]['name']}": len(v)
                                              for bi, v in refail.items()}
            # card then planar: when only cards are left, a card that still streaks takes rule planar (if the recipe
            # allows it). A card is fronto-parallel (every vertex at one forward depth on its rest rays), so planar's
            # in-plane layout is exactly its rest px and its uv becomes the chart's affine rest px -> uv map: the rest
            # frame keeps the chart's paint there, and at a pose the face is a pure scale of an isotropic rest-density
            # texel footprint, which cannot reach the streak test (s1 >= S1_MIN, s1/s2 >= ANISO_MIN) at any reachable
            # pose. What streaks on such a card is its own uv (a face near-edge-on at rest: a sliver of rest px over a
            # full-sized uv triangle; Cove zs_v1 tbcvhall, 9 faces of 2 px rest area). A card that already is planar
            # has no further rule: it is held as above and the build fails closed when only those are left
            if refail and not todo and "planar" in rules:
                for bi, again in refail.items():
                    lay = [lf for lf in again if lf not in (stage.bins[bi].get("planar") or set())]
                    if lay:
                        todo[("planar", bi)] = lay
                if todo:
                    hist[-1]["cardPlanar"] = {f"{stage.bins[bi]['key']}/{stage.bins[bi]['name']}": len(lfs)
                                              for (_r, bi), lfs in todo.items()}
            if planar_held and not todo:
                diag = {}
                for bi, lfs_h in planar_held.items():   # the evidence the next rule needs: what such a face is
                    b = stage.bins[bi]
                    Pw = sc.cpos + (b["v"] / sc.scale) @ sc.C.T
                    fh = b["f"][np.asarray(lfs_h, np.int64)]
                    Pm = Pw[fh.ravel()]
                    Fm = np.arange(len(Pm)).reshape(-1, 3)
                    texm = np.asarray([b["tex"]], np.float64)
                    own = np.zeros(len(Fm), np.int64)
                    uvm = b["uv"][fh.ravel()]
                    rs1, rs2 = SM.face_stretch(sc.cam, Pm, uvm, Fm, own, texm, np.arange(len(Fm)))
                    ws1, ws2, wpose = np.zeros(len(Fm)), np.zeros(len(Fm)), [""] * len(Fm)
                    for cn, cam_ in cams.items():
                        s1, s2 = SM.face_stretch(cam_, Pm, uvm, Fm, own, texm, np.arange(len(Fm)))
                        for j in np.flatnonzero(s1 > ws1):
                            ws1[j], ws2[j], wpose[j] = s1[j], s2[j], cn
                    rx, ry, rz = T.project(sc.cam, Pm)
                    rows_ = []
                    for j, lf in enumerate(lfs_h):
                        a = Pm[3 * j:3 * j + 3]
                        area3 = 0.5 * float(np.linalg.norm(np.cross(a[1] - a[0], a[2] - a[0])))
                        ax = rx[3 * j:3 * j + 3]; ay = ry[3 * j:3 * j + 3]
                        apx = 0.5 * abs(float((ax[1] - ax[0]) * (ay[2] - ay[0]) - (ax[2] - ax[0]) * (ay[1] - ay[0])))
                        rows_.append({"face": int(lf), "failPx": int(ufails.get((bi, lf), 0)), "areaM2": round(area3, 6),
                                      "restAreaPx": round(apx, 3), "restPx": [round(float(ax.mean()), 1),
                                                                             round(float(ay.mean()), 1)],
                                      "z": [round(float(x), 2) for x in rz[3 * j:3 * j + 3]],
                                      "restS1S2": [round(float(rs1[j]), 2), round(float(rs2[j]), 2)],
                                      "worstPose": wpose[j], "worstS1S2": [round(float(ws1[j]), 2), round(float(ws2[j]), 2)]})
                    diag[f"{b['key']}/{b['name']}"] = rows_
                fail("repair: only faces that already have planar uv still stretch, round "
                     f"{rnd} (no stage rule left): " + json.dumps(diag))
            if refail and not todo:
                diag = {}
                for bi, again in refail.items():
                    b = stage.bins[bi]
                    bx, by, bz = T.project(sc.cam, sc.cpos + (b["v"] / sc.scale) @ sc.C.T)
                    rows_ = []
                    for lf in again[:12]:           # the evidence the next rule needs: what such a face is at rest
                        v = b["f"][lf]
                        a_px = 0.5 * abs((bx[v[1]] - bx[v[0]]) * (by[v[2]] - by[v[0]])
                                         - (bx[v[2]] - bx[v[0]]) * (by[v[1]] - by[v[0]]))
                        uv = b["uv"][v] * np.asarray(b["tex"], np.float64)
                        a_tx = 0.5 * abs((uv[1, 0] - uv[0, 0]) * (uv[2, 1] - uv[0, 1])
                                         - (uv[2, 0] - uv[0, 0]) * (uv[1, 1] - uv[0, 1]))
                        rows_.append({"face": int(lf), "failPx": int(fails[(bi, lf)]),
                                      "restShownPx": int(rest_shown.get((bi, lf), 0)),
                                      "restAreaPx": round(float(a_px), 3), "uvAreaTexels": round(float(a_tx), 3),
                                      "z": [round(float(x), 3) for x in bz[v]]})
                    Pw = sc.cpos + (b["v"] / sc.scale) @ sc.C.T
                    fh = b["f"][np.asarray(again[:12], np.int64)]
                    Pm, uvm = Pw[fh.ravel()], b["uv"][fh.ravel()]
                    Fm = np.arange(len(Pm)).reshape(-1, 3)
                    own, texm = np.zeros(len(Fm), np.int64), np.asarray([b["tex"]], np.float64)
                    rs1, rs2 = SM.face_stretch(sc.cam, Pm, uvm, Fm, own, texm, np.arange(len(Fm)))
                    ws1, ws2, wpose = np.zeros(len(Fm)), np.zeros(len(Fm)), [""] * len(Fm)
                    for cn, cam_ in cams.items():
                        s1, s2 = SM.face_stretch(cam_, Pm, uvm, Fm, own, texm, np.arange(len(Fm)))
                        for j in np.flatnonzero(s1 > ws1):
                            ws1[j], ws2[j], wpose[j] = s1[j], s2[j], cn
                    for j, row_ in enumerate(rows_):
                        row_.update(restS1S2=[round(float(rs1[j]), 2), round(float(rs2[j]), 2)], worstPose=wpose[j],
                                    worstS1S2=[round(float(ws1[j]), 2), round(float(ws2[j]), 2)])
                    diag[f"{b['key']}/{b['name']}"] = {"faces": len(again), "first": rows_}
                fail(f"repair: only faces that already are cards still fail, round {rnd} (no stage rule left; a Meshy "
                     f"front or fill face needs the bake; with rule planar these are cards already laid planar): "
                     + json.dumps(diag))
            skipped += len(skip)
            if skip:
                hist[-1]["seamGuardedSkipped"] = len(skip)
            if not todo:
                fail(f"repair: only seam-guarded faces fail ({len(skip)}); no stage rule may touch them")
            # rule planar needs a rest px -> uv map from one of the bin's charts. A bin none of whose charts is a rest
            # projection (the periphery's polar world-space atlas, stronghold_full3d_periphery.piece_uv: Fortress zs_v2
            # 2026-10-02, Mesh_OuterL1, 313 texels off; 2 faces at the frame's left edge, depth 123-313 m, one drawing
            # 2426 px at a pose) has no paint "around where it stands" to re-lay: its unseen faces take rule drop
            # instead, when the recipe allows it and no state shows them at rest (the same premise as a dropped
            # behind-streak face: the backstop shows where it opened, and the next round certifies that). Otherwise the
            # build fails closed as before
            for key in [k for k in todo if k[0] == "planar"]:
                bi = key[1]
                b = stage.bins[bi]
                shown = np.asarray(sorted({lf for (b2, lf) in rest_shown if b2 == bi}), np.int64)
                if not len(shown):
                    continue                        # fails closed below
                bx, by, _ = T.project(sc.cam, sc.cpos + (b["v"] / sc.scale) @ sc.C.T)
                _, maps, off = FL.uv_affine_charts(bx, by, b["f"], b["uv"], shown, b["tex"])
                if maps:
                    continue
                lfs = sorted(todo[key])
                seen = [lf for lf in lfs if rest_shown.get((bi, lf), 0)]
                if "drop" not in rules or seen:
                    fail(f"repair: {b['key']}/{b['name']}: no uv chart is an affine map of rest px (texels off {off}): "
                         f"no map for rule planar, and rule drop " + ("is not allowed" if "drop" not in rules else
                                                                      f"cannot take faces shown at rest {seen[:8]}"))
                del todo[key]
                todo[("drop", bi)] = sorted(set(todo.get(("drop", bi), [])) | set(lfs))
                hist[-1].setdefault("planarNoMapDropped", {})[f"{b['key']}/{b['name']}"] = {
                    "faces": [int(x) for x in lfs], "texelsOff": off}
            by_rule, by_bin = {}, {}
            for (rule, bi), lfs in todo.items():
                by_rule[rule] = by_rule.get(rule, 0) + len(lfs)
                nm = f"{stage.bins[bi]['key'][len(S.PREFIX):]}/{stage.bins[bi]['name']}"
                by_bin[nm] = by_bin.get(nm, 0) + len(lfs)
            hist[-1]["plan"] = {"byRule": by_rule, "flapTorn": len(flap),
                                "topBins": dict(sorted(by_bin.items(), key=lambda x: -x[1])[:8]),
                                "cardRefailHeld": sum(len(v) for v in refail.values())}
            print("PLAN", rnd, json.dumps(hist[-1]["plan"]), flush=True)
            for (rule, bi), lfs in todo.items():                    # cards and planar first (a drop reindexes)
                lfs = np.asarray(sorted(lfs), np.int64)
                if rule == "planar":
                    b = stage.bins[bi]
                    # one affine rest px -> uv map per uv chart (a packed atlas holds several), fitted to the
                    # chart's rest-shown faces; a chart that is no rest projection has none (recorded in the round's
                    # planarNonAffineCharts), and no map at all fails closed. A face takes the map of the
                    # rest-shown face nearest to it in rest px: the paint around where it stands, from the chart that
                    # paints there (an unseen face's own chart may hold no rest px at all: a Meshy body's back-fill
                    # charts, Castle zs_v6 tbcsdock). Fitted afresh each round: drop reindexes faces, planar re-lays them
                    bx, by, _ = T.project(sc.cam, sc.cpos + (b["v"] / sc.scale) @ sc.C.T)
                    shown = np.asarray(sorted({lf for (b2, lf) in rest_shown if b2 == bi}), np.int64)
                    if not len(shown):
                        fail(f"repair: {b['key']}/{b['name']} shows nothing at rest: no rest px -> uv map")
                    ch, maps, off = FL.uv_affine_charts(bx, by, b["f"], b["uv"], shown, b["tex"])
                    if off:
                        hist[-1].setdefault("planarNonAffineCharts", {})[f"{b['key']}/{b['name']}"] = off
                    src = shown[np.isin(ch[shown], list(maps))]
                    if not len(src):
                        fail(f"repair: {b['key']}/{b['name']}: no uv chart is an affine map of rest px (texels off "
                             f"{off}): no map for rule planar")
                    from scipy.spatial import cKDTree
                    cxy = np.stack([bx[b["f"]].mean(1), by[b["f"]].mean(1)], 1)
                    _, near = cKDTree(cxy[src]).query(cxy[lfs])
                    stage.planar(bi, lfs, np.stack([maps[int(ch[src[j]])] for j in near]))
                    planar_n += len(lfs)
                if rule == "card":
                    stage.card(bi, lfs)
                    stage.bins[bi]["carded"] = set(stage.bins[bi].get("carded") or set()) | set(lfs.tolist())
                    carded += len(lfs)
            for (rule, bi), lfs in todo.items():
                if rule == "drop":
                    lfs = np.asarray(sorted(lfs), np.int64)
                    b = stage.bins[bi]
                    remap = np.cumsum(np.isin(np.arange(len(b["f"])), lfs, invert=True)) - 1
                    if bi in env_ground:            # the evidence a later contact failure names (reanchor_after_repair)
                        tw_ = sc.cpos + (b["v"][b["f"][lfs]].reshape(-1, 3) / sc.scale) @ sc.C.T
                        support_drops.extend({"round": rnd, "bin": b["name"], "face": int(lf), "tri": t_.tolist()}
                                             for lf, t_ in zip(lfs.tolist(), tw_.reshape(-1, 3, 3)))
                    stage.drop(bi, lfs)
                    # rest_shown keys of this bin move with the drop
                    rs = {k: v for k, v in rest_shown.items() if k[0] != bi}
                    gone = set(lfs.tolist())
                    for (b2, lf), v in rest_shown.items():
                        if b2 == bi and lf not in gone:
                            rs[(bi, int(remap[lf]))] = v
                    rest_shown = rs
                    if b.get("carded"):
                        b["carded"] = {int(remap[x]) for x in b["carded"] if x not in gone}
                    if b.get("planar"):
                        b["planar"] = {int(remap[x]) for x in b["planar"] if x not in gone}
                    if guarded is not None and bi in guarded:
                        guarded[bi] = np.delete(guarded[bi], lfs)
                    dropped += len(lfs)
            if lips:                                # rule flap: back each torn step with its far side
                n0 = {bi: len(stage.bins[bi]["f"]) for bi in lips}
                fr = build_flaps(sc, T, TP, stage, lips, flap_of, cams)
                flap_rep.append({"round": rnd, "bins": fr})
                flap_faces += len(flap)
                hist[-1]["flapTorn"] = len(flap)
                if guarded is not None:             # flap faces are new and hidden at rest: unguarded
                    for bi in lips:
                        if bi in guarded:
                            guarded[bi] = np.r_[guarded[bi], np.zeros(len(stage.bins[bi]["f"]) - n0[bi], bool)]
        # 5a'. (v2) ground contact on the repaired geometry: a drop may have taken the ground from under an anchored
        # piece. Re-anchor and run the rounds again on that geometry (no prune this cycle), at most REANCHOR_CYCLES
        # times; reanchor_after_repair fails closed when a piece still floats
        if v2:
            ra = reanchor_after_repair(sc, S, T, stage, state_keys, cycle, support_drops)
            if ra is not None:
                reanchor_hist.append(ra)
                print("REANCHOR", json.dumps(ra), flush=True)
                if len(reanchor_hist) > REANCHOR_CYCLES or cycle == last_cycle:
                    fail(f"ground contact: the repair rounds took anchored pieces' ground {len(reanchor_hist)} times "
                         f"(cap {REANCHOR_CYCLES}); each cycle's re-anchor: " + json.dumps(reanchor_hist))
                continue
        certified = stage.geometry_sha()
        # 5a. sky-side prune: the backstop is ground's stand-in. A pose ray that meets it but misses the painted floor
        # plane inside the far cap belongs to the dome (the certificate's ground-hole rule); a backstop triangle only
        # such rays see would draw a band of ground paint in the sky (castle sweep_right: the strip behind the horizon
        # terrain), so it is removed and the dome shows there. Triangles a ground ray sees stay.
        t_pr = time.time()
        sky_t, ground_t, hits = sky_side_hits(sc, T, TP, ZS, stage, state_keys, cams, bs_bi, m)
        t_build = time.time() - t_pr
        # a triangle that only sky rays of the build's cams meet can still be ground for a `final` pose the build does
        # not certify (Dungeon zs_v7 2026-10-02: 1-2 px of hidden ground at loop_228 / transition_002 / 016 / 048 / 075
        # / 087, pose rays through 1 px slits between Mesh_Back_Terrain columns onto backstop triangles the prune had
        # removed): the keep reads the whole certified pose set, as the fill's does. Only candidates are tested
        if sky_t - ground_t:
            if final_masks is None:
                final_masks = {k: ground_ray_px(sc, T, c, ZS.DEVICE) for k, c in final_only.items()}
            ground_t |= final_ground_tris(stage, state_keys, final_only, final_masks, bs_bi)
        if len(prune_keep) != len(stage.bins[bs_bi]["f"]):
            fail(f"sky-side prune: {len(prune_keep)} keep flags for {len(stage.bins[bs_bi]['f'])} backstop triangles")
        prune = np.asarray(sorted(sky_t - ground_t - set(np.nonzero(prune_keep)[0].tolist())), np.int64)
        prune_hist.append({"cycle": cycle, "afterRound": rnd, "skySideTrisPruned": int(len(prune)),
                           "finalPoses": len(final_only), "secondsBuildCams": round(t_build, 1),
                           "secondsTotal": round(time.time() - t_pr, 1)})
        print("PRUNE", json.dumps(prune_hist[-1]), flush=True)
        if not len(prune):
            if seam_weld_on:
                wr = seam_weld(sc, S, stage, rows, cycle)
                weld_hist.append(wr)
                print("SEAM WELD", json.dumps({k: v for k, v in wr.items() if k not in ("passes", "after")} |
                                              {"passes": [{k: v for k, v in p.items() if k not in ("layers", "faces")}
                                                          for p in wr["passes"]]}), flush=True)
                if wr["carded"]:
                    if len(weld_hist) > SEAM_WELD_CYCLES or cycle == last_cycle:
                        fail(f"seam weld: still carding faces after {len(weld_hist)} cycles (cap {SEAM_WELD_CYCLES}): "
                             + json.dumps([{k: v for k, v in w.items() if k != "passes"} for w in weld_hist]))
                    continue
            break
        n_prune += 1
        if n_prune > PRUNE_CYCLES:
            fail(f"sky-side prune: still removing {len(prune)} backstop triangles after {PRUNE_CYCLES} cycles")
        gone = set(prune.tolist())
        remap = np.cumsum(np.isin(np.arange(len(stage.bins[bs_bi]["f"])), prune, invert=True)) - 1
        rest_shown = {(bi, int(remap[lf]) if bi == bs_bi else lf): v for (bi, lf), v in rest_shown.items()
                      if not (bi == bs_bi and lf in gone)}
        stage.drop(bs_bi, prune)
        prune_keep = np.delete(prune_keep, prune)
    kept = np.ones(len(stage.bins[bs_bi]["f"]), bool)   # the last prune removed nothing: every triangle is kept
    # ---- 5b. content: texels of the kept backstop the poses see (every state, every pose), filled from far-side ground
    seen = np.zeros((th, tw), bool)
    for tx, ty, tri, gr in hits:
        ok = (tx >= 0) & (tx < tw) & (ty >= 0) & (ty < th) & kept[tri]
        seen[ty[ok], tx[ok]] = True
    if FF is not None:                  # every fill square's texel: a `final` pose may see it (hidden at rest)
        seen[FF["px"][:, 0] + m["top"], FF["px"][:, 1] + m["left"]] = True
    pad = lambda img: cv2.copyMakeBorder(img, m["top"], m["bottom"], m["left"], m["right"], cv2.BORDER_REPLICATE)
    tex = pad(rgb_env)
    touch = pad(B["touch"].astype(np.uint8)).astype(bool)
    fl = T.Floor(sc.cam)
    wp_env = ZS.world_points(sc.cam, np.where(env_ok, z_env, np.nan))
    hgt = (wp_env - sc.cam["pos"][None, None]) @ fl.n - fl.d
    ground = pad((env_ok & (np.abs(np.nan_to_num(hgt, nan=1e9)) < float(bs.get("groundSrcM", 1.0)))).astype(np.uint8))
    # the frame's own texels only (the border extension is an edge replica: stripes, never a source and filled
    # where a pose sees it); exemplars: environment ground paint (within groundSrcM of the floor plane: a roof or wall
    # is not what lies behind an occluder) outside a HALO_PX ring of the fill, so a tile never copies the texels it
    # replaces. Touching texels are the far surface itself and stay verbatim.
    inframe = np.zeros((th, tw), bool)
    inframe[m["top"]:m["top"] + SC.H, m["left"]:m["left"] + SC.W] = True
    fill = seen & (~touch | ~inframe)
    halo = cv2.dilate(fill.astype(np.uint8), np.ones((2 * HALO_PX + 1,) * 2, np.uint8)).astype(bool)
    src = ground.astype(bool) & inframe & ~halo
    if fill.any():
        q, qrep = L.quilt_fill(tex, fill, src)
        tex = np.where(fill[..., None], q, tex)
    else:
        qrep = {"tiles": 0}
    nrm = L.push_pull(pad(nrm_env), src)
    nrm /= np.maximum(np.linalg.norm(nrm, axis=-1, keepdims=True), 1e-9)
    gxy = B["gridPx"]
    gi = np.clip(gxy[:, 1] + m["top"], 0, th - 1), np.clip(gxy[:, 0] + m["left"], 0, tw - 1)
    nb_world = nrm[gi[0], gi[1]].astype(np.float64)
    if FF is not None:                          # the floor fill is the floor plane: its own normal
        nb_world[B["fillVerts"][0]:B["fillVerts"][1]] = T.Floor(sc.cam).n[None]
    stage.bins[bs_bi]["n"] = sc.local_dir(nb_world)
    Image.fromarray(np.clip(tex, 0, 255).astype(np.uint8)).save(bpath.with_name(f"{BACKSTOP_BIN}_albedo.png"))
    stage.require_certified(certified, "content")
    written = stage.write()
    rows[S.ENV_KEY]["bins"] = sorted(rows[S.ENV_KEY]["bins"] + [row], key=lambda b: b["name"])
    S.ROWS.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    # ---- 5b. bench edits (recipe "edits"; the town bench's own bake runs this same function on a copy of the base)
    edits_rep = apply_edits(S, SM, sc, rows, r, layers_of) if r.get("edits") else None
    # ---- 6. gate on the staged files
    res = gate(S, SC, SM, ZS, sc, r, path, cams, layers_of, work)
    if edits_rep is not None:
        res["edits"] = edits_rep
    if v2:
        res["anchor"] = anchored
        res["removedHidden"] = removed
        res["periphery"] = per_settle
        if rest_own is not None:
            res["restOwner"] = rest_own
        res["reanchor"] = reanchor_hist
        res["seamWeld"] = {"on": seam_weld_on, "iters": SEAM_WELD_ITERS, "cycles": weld_hist}
    if decal is not None:
        res["decal"] = decal
    if paint_order is not None:
        res["paintOrder"] = paint_order
    res.update({"backstop": B["report"] | {"seenTexels": int(seen.sum()), "skySideTrisPruned": sum(c["skySideTrisPruned"] for c in prune_hist), "pruneCycles": prune_hist, "fillTexels": int(fill.sum()),
                                          "sourceTexels": int(src.sum()), "quilt": {k: v for k, v in qrep.items()
                                                                                   if not isinstance(v, (list, np.ndarray))}},
                "repair": {"rounds": hist, "facesDropped": dropped, "facesCarded": carded, "facesPlanar": planar_n,
                           "binsWritten": written,
                           "seamAware": bool(r["repair"].get("seamAware", False)), "seamGuardPx": SEAM_GUARD_PX,
                           "seamGuardedSkipped": skipped,
                           "flap": {"stepEps": FL.STEP_EPS, "hide": FL.FLAP_HIDE, "padPx": FL.FLAP_PAD_PX,
                                    "rmaxPx": FL.FLAP_RMAX_PX, "tornFaces": flap_faces, "rounds": flap_rep,
                                    "nonAffineCharts": flap_charts_off}},
                "seconds": round(time.time() - t0, 1)})
    write_result(S, res)
    if not res["pass"]:
        fail(f"gate: the staged candidate does not pass ({json.dumps(res['summaryByState'])}"
             f"{'; seams: ' + json.dumps(res['seams']['failures']) if (res.get('seams') or {}).get('failures') else ''})")
    print("PASS", json.dumps({k: res[k] for k in ("candidate", "binsSha256", "recipeSha256")}))
    return 0


def apply_edits(S, SM, sc, rows: dict, r: dict, layers_of: dict) -> dict:
    """Step 5b: the recipe's town bench op files (town_bench/bench_edits.py, the bench's own apply) on the staged
    bins, written back; a hide that covers every state building the bin removes the bin from the candidate (a
    partial hide is a bench what-if and fails closed here). -> report {base, ops [{id, sha256, touched}], ...}."""
    if str(HERE / "town_bench") not in sys.path:
        sys.path.insert(0, str(HERE / "town_bench"))
    import bench_edits as E
    files = E.recipe_edits(r)
    state_keys = {s: [S.ENV_KEY] + [S.PREFIX + l for l in ls] for s, ls in layers_of.items()}
    keys = sorted({k for ks in state_keys.values() for k in ks})
    stage = Stage(S, SM, sc, rows, keys)
    ctx = E.Ctx(S, SM, sc, rows, stage, state_keys, hidden={})
    rep = {"base": r["edits"]["base"], "ops": []}
    for d, p in zip(files, r["edits"]["ops"]):
        out = E.apply_file(ctx, d)
        rep["ops"].append({"id": d["id"], "file": p, "sha256": E.op_file_sha(ROOT / p),
                           "touched": [f"{stage.bins[bi]['key']}/{stage.bins[bi]['name']}" for bi in out["touched"]]})
    removed = []
    hidden = {}
    for st, names in ctx.hidden.items():
        for q in names:
            hidden.setdefault(q, set()).add(st)
    for q, sts in sorted(hidden.items()):
        bi = ctx.bin(q)
        need = set(ctx.states_of(bi))
        if sts != need:
            fail(f"edits: hide {q} in {sorted(sts)} only: a bin is built in every state of its prefab "
                 f"({sorted(need - sts)} left); a partial hide is a bench what-if, not a candidate")
        removed.append(q)
    written = stage.write()
    for b in stage.bins:
        if b.get("texDirty"):
            from PIL import Image
            Image.fromarray(b["albedo"]).save(b["path"].with_name(f"{b['name']}_albedo.png"))
            written.append(f"{b['key']}/{b['name']}_albedo.png")
    for q in removed:
        k, name = q.split("/", 1)
        rows[k]["bins"] = [b for b in rows[k]["bins"] if b["name"] != name]
        for suf in (".bytes", "_albedo.png", ".vcol"):
            fp = S.STAGE / k / f"{name}{suf}"
            if fp.exists():
                fp.unlink()
    if removed:
        S.ROWS.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    rep.update({"binsWritten": written, "binsRemoved": removed})
    print("EDITS", json.dumps({"ops": [o["id"] for o in rep["ops"]], "written": len(written), "removed": removed}),
          flush=True)
    return rep


def staged_sha(S, rows: dict, keys: list) -> tuple[str, list]:
    h = hashlib.sha256()
    names = []
    for k in sorted(keys):
        for b in sorted(rows.get(k, {}).get("bins", []), key=lambda b: b["name"]):
            if not b["name"].startswith("Mesh_"):
                continue
            for p in (S.STAGE / k / f"{b['name']}.bytes", S.STAGE / k / f"{b['name']}_albedo.png"):
                if p.is_file():
                    d = p.read_bytes()
                    h.update(f"{k}/{p.name}".encode() + b"\0" + len(d).to_bytes(8, "little") + d)
            names.append(f"{k}/{b['name']}")
    return h.hexdigest(), names


def build_states(SC, r: dict) -> dict:
    """{state: [layers]} the certificate measures: v1, the profile's states (certificate.states, or all of them);
    v2, every state town_full3d_build_states enumerates from the HoMM3 building tree (recorded with its sha)."""
    if r["schema"] == SCHEMA_V2:
        import town_full3d_build_states as BS
        return BS.enumerate_states(SC.FP, SC.layer_map())
    states = r["certificate"].get("states") or list(SC.FP.STATES)
    missing = [s for s in states if s not in SC.FP.STATES]
    if missing:
        fail(f"certificate.states {missing} are not town states {list(SC.FP.STATES)}")
    return {s: list(SC.FP.STATES[s]) for s in states}


def reachable_range(cams: dict) -> dict:
    """The town camera's reachable range, from the installed controller (conflux_town_camera_pan: the cityHuman2
    BhCityCameraController and its SoCityCameraSettings), and what the certificate's poses sample of it. The camera
    is never limited: this records the range the measurement covers, so a narrower pose set cannot pass as the whole."""
    import conflux_town_camera_pan as PAN
    c = PAN.load()
    st = c["settings"]
    return {"source": f"vanilla_city_camera_pan.json ({c['scene']} BhCityCameraController, SoCityCameraSettings "
                      f"{st['name']}; GameAssembly disassembly for the modes)",
            "modes": {"default": "the rest pose",
                      "cursor": f"rest position, yaw +-{st['deltaHorizontalAngle']} deg, pitch +-{st['deltaVerticalAngle']} deg",
                      "free": f"closed spline through {len(st['positionNodes'])} nodes, LookAt(CityCamera pivot)",
                      "transitions": f"lerp / slerp between modes over {st['transitionTime']} s"},
            "sampled": {"poses": len(cams), "names": sorted(cams)},
            "notSampled": "the node-polygon and rest-rotation spline hypotheses, the mode transitions and the 21:9 / "
                          "4096x2160 aspects (conflux_town_camera_pan.poses samples them for the pan envelope only)"}


def gate(S, SC, SM, ZS, sc, r: dict, path: Path, cams: dict, layers_of: dict, work: Path) -> dict:
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    v2 = r["schema"] == SCHEMA_V2
    states = list(layers_of)
    summ = {}
    for s in states:
        keys = [S.ENV_KEY] + [S.PREFIX + l for l in layers_of[s]]
        P, UV, F, owner, names, texs = SM.load_bins(sc, rows, keys)
        (work / s).mkdir(parents=True, exist_ok=True)
        rep = ZS.certify(sc, P, UV, F, owner, names, texs, cams, out=work / s, save_worst=2,
                         sky=ZS.load_sky(sc, rows, keys))
        summ[s] = rep["summary"]
    ok = all(v["maxVisibleBehindPx"] == 0 and v["pass"] and v["groundHoleGrowthPx"] == 0
             and (not v2 or v["maxUnseenFacePx"] == 0) for v in summ.values())
    all_keys = sorted({S.ENV_KEY} | {S.PREFIX + l for s in states for l in layers_of[s]})
    sha, names = staged_sha(S, rows, all_keys)
    extra = {}
    if v2:
        import town_full3d_build_states as BS
        import stronghold_full3d_terrain as T
        import town_full3d_t2_paint as TP
        cg = ground_contact_staged(S)
        rp = rest_paint(S, SC, SM, T, TP, sc, rows, layers_of, r.get("restPaint", {}).get("fxShareOverride"),
                        r.get("restPaint", {}).get("knownGaps"))
        print("REST PAINT", json.dumps({"pass": rp["pass"], "maxComponentPx": rp["maxComponentPx"],
                                        "failing": rp["failing"], "knownGaps": rp["knownGaps"],
                                        "fxExcludedByState": fx_excluded_by_state(rp)}),
              flush=True)
        sm = seams_staged(S, rows)
        if sm is not None:
            print("SEAMS", json.dumps({"pass": sm["pass"], "failures": sm["failures"]}), flush=True)
        ok = ok and cg["pass"] and rp["pass"] and (sm is None or sm["pass"])
        extra = {"buildStates": {"schema": BS.SCHEMA, "count": len(layers_of), "sha256": BS.states_sha(layers_of)},
                 "groundContact": cg, "restPaint": rp, "reachableRange": reachable_range(cams), "seams": sm}
    return {"schema": RESULT_SCHEMA, "faction": r["faction"], "candidate": r["candidate"], "seed": r["seed"],
            "recipe": str(Path(path).resolve().relative_to(ROOT)).replace("\\", "/"), "recipeSha256": recipe_sha(path),
            "certificate": {"schema": "town_zero_streak.v1", "loop": int(r["certificate"].get("loop", 12)),
                            "extraPoses": (EXTRA_POSES_FINAL if r["certificate"].get("extraPoses") == EXTRA_POSES_FINAL
                                           else list(r["certificate"].get("extraPoses", []))),
                            "poses": len(cams), "states": states, "minArea": ZS.MIN_AREA},
            "summaryByState": summ, "pass": bool(ok), "binsSha256": sha, "bins": names, **extra,
            "proofTier": "generated artifact (offline raster of the staged bins); not a Unity render, not bundled"}


def seam_weld_plan(arr: dict, split: np.ndarray, counts: dict | None = None) -> dict:
    """{(seam_face_bin index, local face): slide factor} for repair.seamWeld: the residual (ray) side of every split pair
    whose other side is a Meshy body, slid along its rest rays by the median over its split pairs of (body point's
    rest-camera distance / residual point's). arr: rest_seams(faces=True) in the prefab frame (rest camera at the
    origin); split: building_seam_split's mask. counts: filled with each planned face's number of split pairs."""
    roles = np.asarray(arr["seam_roles"])
    a, b = np.asarray(arr["seam_a"], np.float64), np.asarray(arr["seam_b"], np.float64)
    fbin, flf = np.asarray(arr["seam_face_bin"]), np.asarray(arr["seam_face"])
    da, db = np.linalg.norm(a, axis=1), np.linalg.norm(b, axis=1)
    acc: dict = {}
    for i in np.flatnonzero(np.asarray(split) & (((roles[:, 0] == 0) & (roles[:, 1] == 2)) |
                                                ((roles[:, 0] == 2) & (roles[:, 1] == 0)))):
        j = 0 if roles[i, 0] == 0 else 1
        fac = (db[i] / da[i]) if j == 0 else (da[i] / db[i])
        acc.setdefault((int(fbin[i, j]), int(flf[i, j])), []).append(float(fac))
    if counts is not None:
        counts.update({k: len(v) for k, v in acc.items()})
    return {k: float(np.median(v)) for k, v in acc.items()}


def seam_weld(sc, S, stage: "Stage", rows: dict, cycle: int) -> dict:
    """repair.seamWeld, one cycle: up to SEAM_WELD_ITERS passes of the seams_v2 measure on the in-memory stage and,
    while a layer fails the validator's split rule, a card of each split Body|residual pair's residual face of the
    failing layers onto the body (seam_weld_plan, Stage.card_at); a pass with no failing layer ends it. Fails closed
    without a building-depth pin (nothing to measure) or on a planned face that is not a staged bin's."""
    import stronghold_full3d_buildings as BL
    import town_full3d_building_seams as SEAMS
    if str(ROOT / "tools") not in sys.path:
        sys.path.insert(0, str(ROOT / "tools"))
    import validate_town_scene3d_contract as V
    if BL.building_depth_pin() is None:
        fail("seam weld: the candidate pins no building depth, so there are no building seams to weld")
    rep = json.loads((S.WORK / "stage_report.json").read_text(encoding="utf-8"))
    lids = sorted({k[len(S.PREFIX):] for k in rows if k.startswith(S.PREFIX) and k != S.ENV_KEY})
    of = {f"{b['key']}/{b['name']}": bi for bi, b in enumerate(stage.bins)}
    load = lambda k, name: ((stage.bins[of[f"{k}/{name}"]]["v"], stage.bins[of[f"{k}/{name}"]]["f"])
                            if f"{k}/{name}" in of else None)
    out = {"cycle": cycle, "passes": [], "carded": 0}
    for it in range(SEAM_WELD_ITERS + 1):
        arr = SEAMS.rest_seams(sc, S, rows, rep, lids, None, load=load, faces=True)
        split, _ = V.building_seam_split(arr, True)
        st = V.building_seam_stats(arr)
        failing = sorted(l for l, v in st.items() if v["residualSplit"] > V.BUILDING_SEAM_SPLIT_MIN_PAIRS
                         and v["residualSplitShare"] > V.BUILDING_SEAM_SPLIT_MAX)
        lay = np.asarray([str(x) for x in arr["seam_layers"]])[np.asarray(arr["seam_layer"])] if len(split) else             np.zeros(0, str)
        npairs: dict = {}
        plan = seam_weld_plan(arr, split & np.isin(lay, failing), npairs) if failing and it < SEAM_WELD_ITERS else {}
        p = {"pass": it, "splitPairs": int(sum(v["residualSplit"] for v in st.values())), "failingLayers": failing,
             "layers": {l: v["residualSplit"] for l, v in st.items() if v["residualSplit"]}, "weldFaces": len(plan)}
        if plan:
            fac = np.asarray(list(plan.values()))
            p["factorMinMax"] = [round(float(fac.min()), 4), round(float(fac.max()), 4)]
            # every welded face: its bin, face index (at this pass), slide factor and the split pairs it carried
            p["faces"] = [{"bin": arr["seam_face_bins"][fb], "face": lf, "factor": round(f, 5),
                           "splitPairs": npairs[(fb, lf)]} for (fb, lf), f in sorted(plan.items())]
        out["passes"].append(p)
        if not plan:
            break
        by_bin: dict = {}
        for (fb, lf), f in plan.items():
            nm = arr["seam_face_bins"][fb]
            if nm not in of:
                fail(f"seam weld: split pair face {lf} of {nm} is not a staged bin's (a residual must be a Mesh_ lit bin)")
            by_bin.setdefault(of[nm], []).append((lf, f))
        for bi, lst in by_bin.items():
            lf = np.asarray([x[0] for x in lst], np.int64)
            stage.card_at(bi, lf, np.repeat(np.asarray([x[1] for x in lst], np.float64)[:, None], 3, 1))
        out["carded"] += len(plan)
    out["after"] = out["passes"][-1]
    first = out["passes"][0]["layers"]
    out["layers"] = {l: {"splitBefore": first.get(l, 0), "splitAfter": out["after"]["layers"].get(l, 0)}
                     for l in sorted(set(first) | set(out["after"]["layers"]))}
    return out


def seams_staged(S, rows: dict) -> dict | None:
    """The validator's building seam gate (validate_town_scene3d_contract.building_seam_failures, seams_v2) on the
    staged files, the same measurement building_depth writes into the catalog (town_full3d_building_seams.
    seams_for_build): a seam split fails the build here instead of at the validator after the bundle (Rampart zs_v5 /
    Tower zs_v4, 2026-10-02). None when the candidate pins no building depth (no seams block is written then)."""
    import stronghold_full3d_buildings as BL
    import town_full3d_building_seams as SEAMS
    if str(ROOT / "tools") not in sys.path:
        sys.path.insert(0, str(ROOT / "tools"))
    import validate_town_scene3d_contract as V
    if BL.building_depth_pin() is None:
        return None
    rep = json.loads((S.WORK / "stage_report.json").read_text(encoding="utf-8"))
    lids = sorted({k[len(S.PREFIX):] for k in rows if k.startswith(S.PREFIX) and k != S.ENV_KEY})
    missing = [l for l in lids if l not in (rep.get("buildings") or {})]
    if missing:
        fail(f"seams: prefabs {missing} have no stage_report.buildings row")
    arr, block = SEAMS.seams_for_build(rows, rep, lids)
    fails = V.building_seam_failures({"seams": block}, arr)
    return {"schema": block["schema"], "pass": not fails, "failures": fails,
            "failingLayers": sorted(l for l, v in block["layers"].items()
                                    if v["residualSplit"] > V.BUILDING_SEAM_SPLIT_MIN_PAIRS
                                    and v["residualSplitShare"] > V.BUILDING_SEAM_SPLIT_MAX),
            "layers": block["layers"]}


def ground_contact_staged(S) -> dict:
    """The ground-contact gate re-measured on the staged files (environment bins only; no raster)."""
    import town_full3d_ground_contact as GC
    sc = S.Scene()
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    import town_t2_streak_map as SM
    stage = Stage(S, SM, sc, rows, [S.ENV_KEY])
    cat = json.loads((S.OUT / "catalog.json").read_text(encoding="utf-8"))
    return GC.contact_gate(GC.Scene(sc, stage, S.ENV_KEY, cat))


INSTALLED = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "homm3_town_scene_meshes" / "scene3d"


def installed_catalog(faction: str) -> Path:
    return INSTALLED / f"homm3_{faction}" / "catalog.json"


def final(path: Path) -> int:
    """v2, the one-time gate before install: the certificate at every pose of reachable_cams_full (the loop-36 sweep
    plus the cursor corners, every spline / orientation hypothesis at its extremes and the mode transitions), in
    every build state, on the staged files of a built and passing candidate. Records finalGate in the result;
    `verify` requires it to pass on the very bins it measured once the candidate's catalog is the installed one."""
    import stronghold_full3d_common as SC
    import stronghold_full3d_scene as S
    import town_full3d_zero_streak as ZS
    import town_t2_streak_map as SM
    r = load_recipe(path)
    if r["schema"] != SCHEMA_V2:
        fail(f"final: {path} is not a {SCHEMA_V2} recipe")
    if S.CANDIDATE != r["candidate"]:
        fail(f"final runs inside the candidate {r['candidate']} (TOWN_FULL3D_CANDIDATE={S.CANDIDATE})")
    res_p = S.WORK / "zero_streak_recipe.json"
    res = json.loads(res_p.read_text(encoding="utf-8"))
    if not res.get("pass") or res.get("recipeSha256") != recipe_sha(path):
        fail("final: the candidate's build result does not pass, or is not of this recipe file")
    t0 = time.time()
    sc = S.Scene()
    cams = ZS.reachable_cams_full(sc, FINAL_LOOP)
    layers_of = build_states(SC, r)
    work = S.WORK / "zero_streak_final"
    work.mkdir(parents=True, exist_ok=True)
    g = gate(S, SC, SM, ZS, sc, r, path, cams, layers_of, work)
    if g["binsSha256"] != res["binsSha256"]:
        fail("final: the staged bins are not the ones the build certified")
    res["finalGate"] = {"loop": FINAL_LOOP, "poses": len(cams), "pass": g["pass"], "binsSha256": g["binsSha256"],
                        "summaryByState": g["summaryByState"], "groundContact": g["groundContact"]["pass"],
                        "restPaint": {**{k: g["restPaint"][k] for k in ("pass", "maxComponentPx", "failing", "knownGaps")},
                                      "fxExcludedByState": fx_excluded_by_state(g["restPaint"])},
                        "reachableRange": g["reachableRange"],
                        "seams": None if g.get("seams") is None else {k: g["seams"][k] for k in ("pass", "failures")},
                        "seconds": round(time.time() - t0, 1)}
    write_result(S, res)
    if not g["restPaint"]["pass"]:
        fail("final: the rest frame differs from the painting (rest-paint term) in states "
             + json.dumps({s: g["restPaint"]["byState"][s]["components"][:2] for s in g["restPaint"]["failing"]}))
    if g.get("seams") is not None and not g["seams"]["pass"]:
        fail("final: building seams split (seams_v2): " + json.dumps(g["seams"]["failures"]))
    if not g["pass"]:
        fail("final: the candidate fails the reachable-range certificate: "
             + json.dumps({s: {k: v[k] for k in ("maxVisibleBehindPx", "maxUnseenFacePx", "groundHoleGrowthPx")}
                           for s, v in g["summaryByState"].items()
                           if v["maxVisibleBehindPx"] or v["maxUnseenFacePx"] or v["groundHoleGrowthPx"]}))
    print("FINAL PASS", r["candidate"], len(cams), "poses x", len(layers_of), "states")
    return 0


def rest_paint_cmd(path: Path) -> int:
    """Read-only: the rest-paint term on a staged candidate (TOWN_FULL3D_CANDIDATE, any one: it measures, records
    work/rest_paint.json, and does not touch the build result). Exit 1 when it fails."""
    sys.path.insert(0, str(HERE))
    import stronghold_full3d_common as SC
    import stronghold_full3d_scene as S
    import stronghold_full3d_terrain as T
    import town_full3d_t2_paint as TP
    import town_t2_streak_map as SM
    r = load_recipe(path)
    t0 = time.time()
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    rp = rest_paint(S, SC, SM, T, TP, S.Scene(), rows, build_states(SC, r),
                    r.get("restPaint", {}).get("fxShareOverride"), r.get("restPaint", {}).get("knownGaps"))
    rp.update({"candidate": S.CANDIDATE, "seconds": round(time.time() - t0, 1),
               "proofTier": "generated artifact (offline raster of the staged bins)"})
    (S.WORK / "rest_paint.json").write_text(json.dumps(rp, indent=1), encoding="utf-8")
    print(json.dumps({k: rp[k] for k in ("candidate", "pass", "maxComponentPx", "failing", "knownGaps", "seconds")}))
    print("FX EXCLUDED", json.dumps(fx_excluded_by_state(rp)))
    return 0 if rp["pass"] else 1


def write_result(S, res: dict) -> None:
    (S.WORK / "zero_streak_recipe.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
    sr_path = S.WORK / "stage_report.json"
    sr = json.loads(sr_path.read_text(encoding="utf-8"))
    sr["zeroStreakRecipe"] = {k: res[k] for k in ("schema", "recipe", "recipeSha256", "pass", "binsSha256",
                                                  "proofTier")}
    sr_path.write_text(json.dumps(sr, indent=1), encoding="utf-8")


def verify(path: Path) -> int:
    """Cheap re-check (no raster): the candidate's result passes, was built from this recipe file, and every staged
    bin it measured is byte-identical."""
    r = load_recipe(path)
    if os.environ.get("TOWN_FULL3D_CANDIDATE") != r["candidate"]:
        p = subprocess.run([sys.executable, str(Path(__file__).resolve()), "verify", str(path)], env=_env(r))
        return p.returncode
    sys.path.insert(0, str(HERE))
    import stronghold_full3d_scene as S
    if not S.CAND.is_dir():
        print("VERIFY SKIP", r["candidate"], "is not staged on this machine (artifacts/ is not in git)")
        return 0
    res_p = S.WORK / "zero_streak_recipe.json"
    if not res_p.is_file():
        fail(f"verify: {res_p} missing (build the recipe)")
    res = json.loads(res_p.read_text(encoding="utf-8"))
    if res.get("schema") != RESULT_SCHEMA or not res.get("pass"):
        fail(f"verify: {res_p} is not a passing {RESULT_SCHEMA}")
    if res["recipeSha256"] != recipe_sha(path):
        fail(f"verify: {path} changed since the candidate was built (rebuild it)")
    for s, v in res["summaryByState"].items():
        if v["maxVisibleBehindPx"] != 0 or v["groundHoleGrowthPx"] != 0:
            fail(f"verify: state {s} recorded {v['maxVisibleBehindPx']} visible px / {v['groundHoleGrowthPx']} ground")
    if r["schema"] == SCHEMA_V2:
        # the build-state set is re-derived from the tree (it cannot shrink silently), the unseen-face term must be
        # zero in every state, and the ground contact is re-measured on the staged files
        import stronghold_full3d_common as SC
        import town_full3d_build_states as BS
        layers_of = build_states(SC, r)
        bs = res.get("buildStates") or {}
        if bs.get("sha256") != BS.states_sha(layers_of) or sorted(res["summaryByState"]) != sorted(layers_of):
            fail(f"verify: the certified build states ({bs.get('count')}, sha {str(bs.get('sha256'))[:12]}) are not "
                 f"the tree's ({len(layers_of)}, sha {BS.states_sha(layers_of)[:12]}): rebuild")
        bad = {s: v.get("maxUnseenFacePx") for s, v in res["summaryByState"].items() if v.get("maxUnseenFacePx") != 0}
        if bad:
            fail(f"verify: unseen-face stretch recorded in {bad}")
        cg = ground_contact_staged(S)
        if not cg["pass"] or not (res.get("groundContact") or {}).get("pass"):
            fail("verify: the ground-contact gate does not pass on the staged files "
                 + json.dumps({k: v for k, v in cg["byBin"].items() if v["floating"] or v["unsupported"]}))
        fg = res.get("finalGate")
        inst = installed_catalog(r["faction"])
        if inst.is_file() and (S.OUT / "catalog.json").is_file() and \
                inst.read_bytes() == (S.OUT / "catalog.json").read_bytes():
            if not fg or not fg.get("pass") or fg.get("binsSha256") != res["binsSha256"]:
                fail(f"verify: {r['candidate']} is the installed {r['faction']} scene but has no passing final gate "
                     f"on its certified bins (town_full3d_recipe.py final)")
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    keys = sorted({b.split("/", 1)[0] for b in res["bins"]})
    sha, _ = staged_sha(S, rows, keys)
    if sha != res["binsSha256"]:
        fail(f"verify: staged bins of {r['candidate']} differ from the certified ones (sha {sha[:12]} vs "
             f"{res['binsSha256'][:12]}): re-run the recipe build on a fresh candidate")
    fg = res.get("finalGate")
    print("VERIFY OK", r["candidate"], sha[:12], r["schema"],
          "final " + ("pass" if fg and fg.get("pass") and fg.get("binsSha256") == sha else "absent"))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "verify", "final", "rest-paint", "_finish", "_catalog"])
    ap.add_argument("recipe")
    a = ap.parse_args()
    p = Path(a.recipe)
    if not p.is_absolute():
        p = ROOT / p
    if a.cmd == "build":
        return build(p)
    if a.cmd == "verify":
        return verify(p)
    if a.cmd == "_catalog":
        return catalog(p)
    if a.cmd == "rest-paint":
        return rest_paint_cmd(p)
    if a.cmd == "final":
        r = load_recipe(p)
        if os.environ.get("TOWN_FULL3D_CANDIDATE") != r["candidate"]:
            q = subprocess.run([sys.executable, str(Path(__file__).resolve()), "final", str(p)], env=_env(r))
            return q.returncode
        sys.path.insert(0, str(HERE))
        return final(p)
    return finish(p)


if __name__ == "__main__":
    raise SystemExit(main())
