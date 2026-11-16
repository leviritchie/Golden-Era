"""Patch a def_retarget GLB in numpy: the Blender-free delivery stage for localized skin / track fixes.

    python tools/homm3_glb_patch/patch_glb.py apply <unit> [--glb P] [--out P]   # exit 3 = no "glbPatch" in the config
    python tools/homm3_glb_patch/patch_glb.py parity <unit> [--glb P]            # numpy CS vs Blender's stored targets
    python tools/homm3_glb_patch/patch_glb.py check <glb...>                     # stamp shape

The unit config's "glbPatch" ({"reason", "ops": [...]}) is applied to the verified export (the first delivery stage,
before deyaw / stride match / ground: tools/validate_homm3_def_retarget_emphasis_contract.DELIVERY_STAGES), so every
later stage measures the patched body. Ops (docs/homm3_glb_patch_lane.md):
  moveWeights  hand all but `keep` of the listed bones' skin weight to bone `to` on the vertices of a region, a product
               of ramps on rest-space coordinates ("space": "blender" = build_unit's body axes x, -z_gltf, y_gltf, the
               axes the build hooks measure in); the 4-influence cap keeps the largest four, renormalised.
               Optional "onlyWith": {"bones": [...], "atLeast": w} limits it to vertices already carrying at least w
               on those bones (a mixed-weight chip at a cut, not the pure verts beside it).
  rotateTrack  post-multiply a bone's local rotation keys by a fixed axis-angle offset (bone-local axis) in the listed
               clips, on the channel's own key grid and interpolation.
  sitRepose    re-pose a planted sit: per listed clip and weight shape (full / easeOut / easeIn / bracket over the clip,
               the quadrupedSit ease shapes), turn the hips' world transform by `pitch` deg about the world lateral
               axis (glTF +x; positive leans toward +z, the unit's front) through the hind hips' mid-point, lower it by
               `drop` x body height, two-bone IK each hind leg back to its own hock (knee bend kept on its original
               side, foot and toes keep their world rotation), then turn each `turns` bone's subtree by deg x weight
               about its own head on the same axis, parents first. Optional "foreLegs" {chains: [[upper, lower, hand]],
               reach}: after the turns, two-bone IK each foreleg so its hand stands on the floor where the bind pose
               (the rig's standing quadruped) puts it (the bind hand's height over the bind hind feet, carried by
               the key's own hind-foot height; its lateral offset from the upper bone; `reach` x body height forward
               of the re-posed upper bone), the elbow bent toward the back (-z),
               the hand turned to its bind world rotation; blended from the clip's own pose by the clip's weight.
               Written LINEAR on the clip's union key grid.
  keyRotations post-multiply listed bones' local rotation keys by per-key offset quaternions from a sha256-pinned
               table (tools/homm3_glb_patch/key_rotations/<name>.json, schema homm3_glb_patch_key_rotations.v1:
               {clips: {clip: {bone: {times, quat}}}}) whose times must be the channel's own key grid at that point
               of the op list (refused otherwise, and past 120 deg per key); the per-frame forelimb articulation
               fitted offline to the DEF plates is delivered this way (docs/homm3_glb_patch_lane.md).
  setWeights   replace listed vertices' skin weights from a sha256-pinned table in the same directory (schema
               homm3_glb_patch_weight_table.v1: {vertexCount, vertices: {index: {bone: weight}}}, 1-4 bones each,
               summing to 1); carries an offline per-vertex re-solve (a raised arm's shoulder/armpit).
  keyTranslations add per-time [dx, dy, dz] deltas from a sha256-pinned table in the same directory (schema
               homm3_glb_patch_key_translations.v1: {clips: {clip: {bone: {times, delta}}}}) to listed bones'
               translation keys, interpolated onto the channel's own grid, refused past 0.25 x the body height per
               key; carries a fitted root (Hips) path across a rebuild whose build-time offset fit moved it.
  keyScales    multiply listed bones' scale keys by per-time [sx, sy, sz] factors (bone-local; a glTF bone runs along
               local +y) from a sha256-pinned table in the same directory (schema homm3_glb_patch_key_scales.v1:
               {clips: {clip: {bone: {times, factor}}}}, each factor in [0.5, 2]); a channel on another grid is
               resampled onto the table's (same first..last key). Children inherit the scale: a stub arm lengthened
               into a punch (h3_air_elemental).
  setTracks    replace listed bones' translation / rotation / scale keys of whole clips from a sha256-pinned table in
               the same directory (schema homm3_glb_patch_tracks.v1: {clips: {clip: {times, bones: {bone:
               {translation?, rotation?, scale?}}}}}); times must be the clip's own key grid (so the master frame
               mapping and the one-key-per-CS-target rule hold), rotations unit quaternions, scales within the
               keyScales range. Carries a clip authored offline on the shipped rig (the flyer flights: h3_roc).
               "clearCorrectives": true zeroes the CS targets of the table's clips instead of re-baking them (a clip
               authored and approved on the plain skin; a differential re-bake of correctives fitted to the replaced
               pose pulls layered feathers through each other); stretchRelax and the tear gate then run on those.
  addJoints    append new bones to the rig from a sha256-pinned table in the same directory (schema
               homm3_glb_patch_joints.v1: {jointCount, joints: [{name, parent, head: [x, y, z]}]}): jointCount pins the
               skin's joint count the table was authored on; each joint is a new node under `parent` (a skin joint or
               an earlier joint of the table), at rest-space `head` with the identity bind rotation, appended to the
               END of the skin's joint list (existing JOINTS_0 indices stay valid) with its inverse bind matrix, and
               held at its rest TRS by 2-key STEP channels in every clip (as the export holds a static bone), so old
               clips carry it rigidly with its parent. Later setWeights / setTracks ops may name the new joints.
  cutFaces     drop triangles of the body from a sha256-pinned table in the same directory (schema
               homm3_glb_patch_face_cut.v1: {faceCount, indexSha256, faces: [face index, ...]}): indexSha256 pins the
               export's index buffer bytes, faces are rows of it. Vertices, UVs, normals and morph targets are kept
               (the CS targets stay per-vertex); only the index buffer shrinks. For a part modelled fused to another
               (a tail to a calf) whose bridging triangles stretch into a web. Refused: more than CUT_MAX_SHARE of the
               faces, a vertex left in no face, a second cutFaces op. The patch then declares the topology change in
               its stamp ("topology") and proves vertex data byte-identical and the kept triangles the export's own.
After the ops, <unit>_DEF_Master (the whole reel, the GLB's first animation, what viewers play) is rebuilt from the
patched Unit_* clips with build_unit.py's clip-to-master frame mapping (master_sequence.json: Unit_<contractSuffix> is the
longest segment of that suffix, its key i is master frame globalStart + i; a bookend / shorter segment frame takes the
Unit frame showing the same DEF PNG), so the master shows exactly what ships; frames with no shipped counterpart keep
their keys and are listed in the stamp's masterSync. The CS targets of the master are re-baked with the rest.
Every op leaves POSITION, NORMAL, TEXCOORD_0 and images byte-identical, and every op but cutFaces the indices (checked:
the look's geometry hash and base colour stay valid, so look.py --stages apply re-delivers the stamped texture without
a re-bake; after a cutFaces the look accepts the delivery only through declared_cut_errors: the same vertex data and
the retained base's triangles in order, minus exactly the stamped number of faces).
The Corrective Smooth morph targets (bake_cs.py) are re-baked differentially in numpy (cs_numpy.py): per target,
stored + (CS(new skin/pose) - CS(old skin/pose)), bit-identical where the difference is below 1e-7, after a parity
proof that numpy CS on the input reproduces Blender's stored targets (PARITY_P99_MAX of the body height; refused past it)
on the conditioned vertices (cs_numpy.COND_EDGE: where Blender's own frames are float32 noise nothing reproduces its bytes;
those vertices get the same differential rule and are counted in csRebake, and the later delivery gates measure them).
Refuses: an already patched GLB, an unknown op or key, a bone or clip the GLB lacks, a region that selects nothing, a
non-identity body/rig node transform, a weld group whose members the op would split, a sparse or shared accessor it
would overwrite, and an output whose geometry or image hash changed.
Stamps asset.extras.homm3DefRetargetDeliveryPatch {schema, sourceGlbSha256, configSha256, ops, csRebake} and writes
<glb>.patch.json with the source and output sha (the delivery chain's link). Proof tier: generated artifact.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools/homm3_def_retarget_delivery"))
sys.path.insert(0, str(ROOT / "tools/homm3_def_retarget"))
import cs_numpy as CS  # noqa: E402
import skip_def_groups  # noqa: E402
import stage_sidecar  # noqa: E402
import stride_gait as G  # noqa: E402
from stride_match_glb import Glb, write_channels  # noqa: E402

STAMP = "homm3DefRetargetDeliveryPatch"
SCHEMA = "homm3_def_retarget_delivery_patch.v1"
CONFIG_KEY = "glbPatch"
PARITY_P99_MAX = 0.002        # numpy CS vs Blender's stored targets, p99 over vertices x targets, / body height
PARITY_MAX_MAX = 0.02         # and the single worst vertex
STRETCH_RATIO = 2.0           # an edge longer than this x its rest length counts as torn (the render gate's measure)
WORST_STRETCH_SLACK = 1.05    # the patched body's worst edge stretch may not exceed the input's by more than this
KEEP_EPS = 1e-7
MOCAP_RUNS = ROOT / "artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/runs"
MASTER_SUFFIX = "_DEF_Master"
MASTER_COPY_TOL_DEG = 0.01    # the synced master must match the shipped Unit_* pose of each mapped frame within this
MASTER_COPY_TOL_POS = 1e-5    # (joint world rotation, degrees) and this (joint world position, fraction of body height)
OPS = {"moveWeights": {"op", "from", "to", "region", "keep", "space", "onlyWith", "note"},
       "rotateTrack": {"op", "bone", "clips", "axis", "deg", "note"},
       "sitRepose": {"op", "clips", "pitch", "drop", "hips", "legs", "turns", "foreLegs", "note"},
       "keyRotations": {"op", "table", "sha256", "regrid", "note"},
       "keyTranslations": {"op", "table", "sha256", "regrid", "note"},
       "keyScales": {"op", "table", "sha256", "note"},
       "setTracks": {"op", "table", "sha256", "clearCorrectives", "note"},
       "diffuseWeights": {"op", "bones", "iterations", "alpha", "region", "note"},
       "setWeights": {"op", "table", "sha256", "note"},
       "addJoints": {"op", "table", "sha256", "note"},
       "cutFaces": {"op", "table", "sha256", "note"},
       "stretchRelax": {"op", "clips", "ratio", "iterations", "smooth", "bones", "maxMove", "note"}}
WEIGHT_TABLE_SCHEMA = "homm3_glb_patch_weight_table.v1"
KEY_ROT_SCHEMA = "homm3_glb_patch_key_rotations.v1"
KEY_ROT_DIR = "tools/homm3_glb_patch/key_rotations"
KEY_TR_SCHEMA = "homm3_glb_patch_key_translations.v1"
KEY_SC_SCHEMA = "homm3_glb_patch_key_scales.v1"
TRACKS_SCHEMA = "homm3_glb_patch_tracks.v1"
JOINTS_SCHEMA = "homm3_glb_patch_joints.v1"
FACE_CUT_SCHEMA = "homm3_glb_patch_face_cut.v1"
CUT_MAX_SHARE = 0.1           # cutFaces: at most this share of the body's triangles (a seam between fused parts, not a remesh)
JOINT_HEAD_MARGIN = 0.5       # addJoints: a head farther than this x the body height outside the rest bounds is refused
MAX_SKIN_JOINTS = 255         # JOINTS_0 is unsigned bytes in these exports
TRACK_PATHS = {"translation": 3, "rotation": 4, "scale": 3}
KEY_SC_RANGE = (0.5, 2.0)     # one key's scale factor per axis; outside it the table is refused (2x is the tear line)
KEY_TR_MAX_OVER_H = 0.25      # one key's translation delta, / body height; past it the table is refused
KEY_ROT_MAX_DEG = 120.0       # one key's offset; past it the table is refused (a fit that ran away)
KEY_ROT_TIME_EPS = 1e-5
FORE_KEYS = {"chains", "reach"}
SIT_SHAPES = ("full", "easeOut", "easeIn", "bracket")
SIT_LEGS = [["LeftUpLeg", "LeftLeg", "LeftFoot"], ["RightUpLeg", "RightLeg", "RightFoot"]]
RAMP_KEYS = {"axis", "above", "below", "ramp"}
RELAX_MAX_MOVE = 0.05         # stretchRelax default: no weld group may slide farther than this x the body height


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def canonical_sha(obj) -> str:
    return sha(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def unit_config(unit: str) -> dict:
    p = ROOT / "tools/homm3_def_retarget/units" / f"{unit}.json"
    if not p.is_file():
        raise SystemExit(f"{unit}: no unit config at {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def canonical_glb(unit: str) -> Path:
    return ROOT / "artifacts/homm3_def_retarget" / unit / f"{unit}_def_retarget.glb"


def spec_errors(spec) -> list[str]:
    """Schema errors of a "glbPatch" block ([] = valid). Shared with the validator."""
    if not isinstance(spec, dict) or set(spec) - {"reason", "ops"}:
        return [f"{CONFIG_KEY} must be {{reason, ops}}, got keys {sorted(spec) if isinstance(spec, dict) else spec!r}"]
    bad = []
    if not str(spec.get("reason", "")).strip():
        bad.append(f"{CONFIG_KEY}.reason is empty")
    ops = spec.get("ops")
    if not isinstance(ops, list) or not ops:
        return bad + [f"{CONFIG_KEY}.ops must be a non-empty list"]
    for i, op in enumerate(ops):
        kind = op.get("op") if isinstance(op, dict) else None
        if kind not in OPS:
            bad.append(f"ops[{i}]: unknown op {kind!r} (known: {sorted(OPS)})")
            continue
        extra = set(op) - OPS[kind]
        if extra:
            bad.append(f"ops[{i}] {kind}: unknown keys {sorted(extra)}")
        if kind == "diffuseWeights":
            if not (isinstance(op.get("bones"), list) and op["bones"] and all(isinstance(x, str) for x in op["bones"])):
                bad.append(f"ops[{i}] diffuseWeights: 'bones' must be a non-empty list of bone names / globs")
            if not (isinstance(op.get("iterations"), int) and 1 <= op["iterations"] <= 50):
                bad.append(f"ops[{i}] diffuseWeights: iterations must be an int in [1, 50]")
            if not (isinstance(op.get("alpha"), (int, float)) and 0.0 < op["alpha"] <= 1.0):
                bad.append(f"ops[{i}] diffuseWeights: alpha must be in (0, 1]")
        elif kind == "moveWeights":
            if not (isinstance(op.get("from"), list) and op["from"] and all(isinstance(x, str) for x in op["from"])):
                bad.append(f"ops[{i}] moveWeights: 'from' must be a non-empty list of bone names / globs")
            if not isinstance(op.get("to"), str):
                bad.append(f"ops[{i}] moveWeights: 'to' must be a bone name")
            if op.get("space", "blender") != "blender":
                bad.append(f"ops[{i}] moveWeights: space must be 'blender'")
            k = op.get("keep", 0.0)
            if not isinstance(k, (int, float)) or not 0.0 <= k < 1.0:
                bad.append(f"ops[{i}] moveWeights: keep must be in [0, 1)")
            ow = op.get("onlyWith")
            if ow is not None and not (isinstance(ow, dict) and set(ow) == {"bones", "atLeast"}
                                       and isinstance(ow["bones"], list) and ow["bones"]
                                       and all(isinstance(x, str) for x in ow["bones"])
                                       and isinstance(ow["atLeast"], (int, float)) and 0.0 < ow["atLeast"] <= 1.0):
                bad.append(f"ops[{i}] moveWeights: onlyWith must be {{bones: [names/globs], atLeast: (0, 1]}}")
            reg = op.get("region")
            if not isinstance(reg, list) or not reg:
                bad.append(f"ops[{i}] moveWeights: region must be a non-empty list of ramps")
            else:
                for r in reg:
                    if not isinstance(r, dict) or set(r) - RAMP_KEYS or r.get("axis") not in ("x", "y", "z") \
                            or (("above" in r) == ("below" in r)) or not isinstance(r.get("ramp"), (int, float)) \
                            or r["ramp"] <= 0:
                        bad.append(f"ops[{i}] moveWeights: bad ramp {r!r} (axis x|y|z, exactly one of above/below, "
                                   "ramp > 0)")
        elif kind == "sitRepose":
            bad += [f"ops[{i}] sitRepose: {e}" for e in sit_repose_errors(op)]
        elif kind == "keyRotations":
            bad += [f"ops[{i}] keyRotations: {e}" for e in key_rotations_table(op)[1]]
            if "regrid" in op and not isinstance(op["regrid"], bool):
                bad.append(f"ops[{i}] keyRotations: regrid must be true or false")
        elif kind == "setWeights":
            bad += [f"ops[{i}] setWeights: {e}" for e in weight_table(op)[1]]
        elif kind == "addJoints":
            bad += [f"ops[{i}] addJoints: {e}" for e in joints_table(op)[1]]
        elif kind == "cutFaces":
            bad += [f"ops[{i}] cutFaces: {e}" for e in face_cut_table(op)[1]]
            if any(isinstance(o, dict) and o.get("op") == "cutFaces" for o in ops[:i]):
                bad.append(f"ops[{i}] cutFaces: a second cutFaces op (one table pins the export's index buffer)")
        elif kind == "stretchRelax":
            bad += [f"ops[{i}] stretchRelax: {e}" for e in stretch_relax_errors(op)]
            if any(isinstance(o, dict) and o.get("op") != "stretchRelax" for o in ops[i + 1:]):
                bad.append(f"ops[{i}] stretchRelax: must come after every other op (it corrects the re-baked CS "
                           "targets, after all skin and track edits)")
        elif kind == "keyScales":
            bad += [f"ops[{i}] keyScales: {e}" for e in key_scales_table(op)[1]]
        elif kind == "setTracks":
            bad += [f"ops[{i}] setTracks: {e}" for e in tracks_table(op)[1]]
            if "clearCorrectives" in op and not isinstance(op["clearCorrectives"], bool):
                bad.append(f"ops[{i}] setTracks: clearCorrectives must be true or false")
        elif kind == "keyTranslations":
            bad += [f"ops[{i}] keyTranslations: {e}" for e in key_translations_table(op)[1]]
            if "regrid" in op and not isinstance(op["regrid"], bool):
                bad.append(f"ops[{i}] keyTranslations: regrid must be true or false")
        else:
            if not isinstance(op.get("bone"), str):
                bad.append(f"ops[{i}] rotateTrack: 'bone' must be a bone name")
            if not (isinstance(op.get("clips"), list) and op["clips"] and all(isinstance(c, str) for c in op["clips"])):
                bad.append(f"ops[{i}] rotateTrack: 'clips' must be a non-empty list of clip names")
            ax = op.get("axis")
            if not (isinstance(ax, list) and len(ax) == 3 and all(isinstance(x, (int, float)) for x in ax)
                    and np.linalg.norm(ax) > 1e-9):
                bad.append(f"ops[{i}] rotateTrack: axis must be a non-zero [x, y, z]")
            if not isinstance(op.get("deg"), (int, float)) or not 0 < abs(op["deg"]) <= 90:
                bad.append(f"ops[{i}] rotateTrack: deg must be non-zero and within +-90")
    return bad


def stretch_relax_errors(op: dict) -> list[str]:
    bad = []
    if not (isinstance(op.get("clips"), list) and op["clips"] and all(isinstance(c, str) for c in op["clips"])):
        bad.append("'clips' must be a non-empty list of clip names")
    r = op.get("ratio")
    if not (isinstance(r, (int, float)) and not isinstance(r, bool) and 1.2 <= r < STRETCH_RATIO):
        bad.append(f"ratio must be in [1.2, {STRETCH_RATIO}) (the length it limits edges to, under the tear gate's)")
    it = op.get("iterations")
    if not (isinstance(it, int) and not isinstance(it, bool) and 1 <= it <= 5000):
        bad.append("iterations must be an int in [1, 5000]")
    sm = op.get("smooth")
    if not (isinstance(sm, (int, float)) and not isinstance(sm, bool) and 0.0 <= sm <= 1.0):
        bad.append("smooth must be in [0, 1]")
    if "bones" in op and not (isinstance(op["bones"], list) and op["bones"]
                              and all(isinstance(x, str) for x in op["bones"])):
        bad.append("'bones' must be a non-empty list of bone names / globs")
    mm = op.get("maxMove", RELAX_MAX_MOVE)
    if not (isinstance(mm, (int, float)) and not isinstance(mm, bool) and 0.0 < mm <= 0.1):
        bad.append("maxMove must be in (0, 0.1] (a fraction of the body height)")
    return bad


def sit_repose_errors(op: dict) -> list[str]:
    bad = []
    cl = op.get("clips")
    if not (isinstance(cl, dict) and cl and all(isinstance(c, str) and v in SIT_SHAPES for c, v in cl.items())):
        bad.append(f"'clips' must be a non-empty {{clip: shape}} map, shape one of {list(SIT_SHAPES)}")

    def num(v):
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if not num(op.get("pitch", 0)) or abs(op.get("pitch", 0)) > 60:
        bad.append("pitch must be a number within +-60 deg")
    if not num(op.get("drop", 0)) or not 0.0 <= op.get("drop", 0) <= 0.3:
        bad.append("drop must be in [0, 0.3] of the body height")
    if not isinstance(op.get("hips", "Hips"), str):
        bad.append("hips must be a bone name")
    legs = op.get("legs", SIT_LEGS)
    if not (isinstance(legs, list) and legs and all(isinstance(c, list) and len(c) == 3
                                                     and all(isinstance(b, str) for b in c) for c in legs)):
        bad.append("legs must be a non-empty list of [upper, lower, foot] bone names")
    tr = op.get("turns", [])
    if not (isinstance(tr, list) and all(isinstance(t, dict) and set(t) == {"bone", "deg"} and isinstance(t["bone"], str)
                                         and num(t["deg"]) and 0 < abs(t["deg"]) <= 120 for t in tr)):
        bad.append("turns must be a list of {bone, deg} with 0 < |deg| <= 120")
    elif not op.get("pitch") and not op.get("drop") and not tr and "foreLegs" not in op:
        bad.append("pitch, drop, turns and foreLegs are all empty (a no-op)")
    if "foreLegs" in op:
        fl = op["foreLegs"]
        if not (isinstance(fl, dict) and set(fl) == FORE_KEYS):
            bad.append(f"foreLegs must be {{{', '.join(sorted(FORE_KEYS))}}}")
        else:
            ch = fl["chains"]
            if not (isinstance(ch, list) and ch and all(isinstance(c, list) and len(c) == 3
                                                         and all(isinstance(b, str) for b in c) for c in ch)):
                bad.append("foreLegs.chains must be a non-empty list of [upper, lower, hand] bone names")
            elif isinstance(tr, list) and {b for c in ch for b in c} & {t.get("bone") for t in tr if isinstance(t, dict)}:
                bad.append("a foreLegs bone is also a turn bone (the IK owns it)")
            if not num(fl["reach"]) or abs(fl["reach"]) > 0.3:
                bad.append("foreLegs.reach must be a number within +-0.3 of the body height")
    return bad


def key_rotations_table(op: dict) -> tuple[dict | None, list[str]]:
    """(table, schema errors) of a keyRotations op: a repo file under KEY_ROT_DIR pinned by its sha256, holding per
    clip, per bone the channel's own key times and one unit xyzw offset quaternion per key."""
    t = op.get("table")
    if not (isinstance(t, str) and t.replace("\\", "/").startswith(KEY_ROT_DIR + "/") and t.endswith(".json")
            and ".." not in t):
        return None, [f"table must be a repo-relative {KEY_ROT_DIR}/<name>.json path"]
    p = ROOT / t
    if not p.is_file():
        return None, [f"table {t} does not exist"]
    raw = p.read_bytes()
    if op.get("sha256") != sha(raw):
        return None, [f"sha256 is not the table's ({sha(raw)}): re-pin it after editing {t}"]
    try:
        tab = json.loads(raw.decode("utf-8"))
    except ValueError as e:
        return None, [f"table {t} is not JSON ({e})"]
    bad = []
    if tab.get("schema") != KEY_ROT_SCHEMA:
        bad.append(f"table schema must be {KEY_ROT_SCHEMA}")
    cl = tab.get("clips")
    if not (isinstance(cl, dict) and cl):
        return tab, bad + ["table clips must be a non-empty {clip: {bone: {times, quat}}} map"]
    for c, bones in cl.items():
        if not (isinstance(bones, dict) and bones):
            bad.append(f"{c}: no bones"); continue
        for b, ch in bones.items():
            if not (isinstance(ch, dict) and set(ch) == {"times", "quat"}):
                bad.append(f"{c} {b}: must be {{times, quat}}"); continue
            tt, q = np.asarray(ch["times"], float), np.asarray(ch["quat"], float)
            if tt.ndim != 1 or not len(tt) or q.shape != (len(tt), 4) or np.any(np.diff(tt) < -KEY_ROT_TIME_EPS):
                bad.append(f"{c} {b}: times must be a non-decreasing list with one [x, y, z, w] per time"); continue
            if np.abs(np.linalg.norm(q, axis=1) - 1).max() > 1e-4:
                bad.append(f"{c} {b}: offset quaternions must be unit")
            elif np.degrees(2 * np.arccos(np.clip(np.abs(q[:, 3]), 0, 1))).max() > KEY_ROT_MAX_DEG:
                bad.append(f"{c} {b}: an offset exceeds {KEY_ROT_MAX_DEG} deg")
    return tab, bad


def op_key_rotations(g: Glb, op: dict) -> dict:
    """Post-multiply each listed bone's local rotation keys by the table's per-key offsets, on the channel's own key
    grid (the table's times must be that grid, or with regrid: true a denser grid spanning the same first..last key)
    and interpolation."""
    tab, bad = key_rotations_table(op)
    if bad:
        raise SystemExit(f"keyRotations: {'; '.join(bad)}")
    if "regrid" in op and not isinstance(op["regrid"], bool):
        raise SystemExit("keyRotations: regrid must be true or false")
    done, worst, regridded = {}, 0.0, {}
    for clip, bones in tab["clips"].items():
        a = g.anim(clip)
        for bone, ch in bones.items():
            if bone not in g.names:
                raise SystemExit(f"keyRotations: no node {bone!r}")
            node = g.names.index(bone)
            cs = [c for c in a["channels"] if c["target"]["node"] == node and c["target"]["path"] == "rotation"]
            if len(cs) != 1:
                raise SystemExit(f"keyRotations: {clip} has {len(cs)} rotation channels on {bone} (needs exactly one)")
            s = a["samplers"][cs[0]["sampler"]]
            it = s.get("interpolation", "LINEAR")
            if it not in ("LINEAR", "STEP"):
                raise SystemExit(f"keyRotations: {clip} {bone} rotation is {it}; LINEAR and STEP only")
            t = g.read(s["input"])[:, 0]
            tt = np.asarray(ch["times"], float)
            r = g.read(s["output"])
            r = r / np.linalg.norm(r, axis=1, keepdims=True)
            if len(t) != len(tt) or np.abs(t - tt).max() > KEY_ROT_TIME_EPS:
                # regrid: a sparse channel (e.g. a 2-key static hold) is resampled onto the table's denser grid, which
                # must span exactly the channel's own first..last key so the clip length cannot change
                if not (op.get("regrid") is True and abs(tt[0] - t[0]) <= KEY_ROT_TIME_EPS
                        and abs(tt[-1] - t[-1]) <= KEY_ROT_TIME_EPS):
                    raise SystemExit(f"keyRotations: {clip} {bone}: the table's times are not the channel's key grid "
                                     f"({len(tt)} vs {len(t)} keys); refit the table on this GLB"
                                     + ("" if op.get("regrid") is True else " or set regrid: true"))
                r = resample_rot(t, r, tt, it)   # STEP holds are sampled as holds, then written LINEAR on the
                t, it = tt, "LINEAR"              # denser grid (a jump becomes a one-grid-step ramp; idle retime
                                                  # takes LINEAR only)
                regridded.setdefault(clip, []).append(bone)
            q = np.asarray(ch["quat"], float)
            q = q / np.linalg.norm(q, axis=1, keepdims=True)
            new = np.stack([qmul(r[i:i + 1], q[i])[0] for i in range(len(t))])
            write_channels(g, a, t, {(node, "rotation"): new}, it)
            done.setdefault(clip, {})[bone] = len(t)
            worst = max(worst, float(np.degrees(2 * np.arccos(np.clip(np.abs(q[:, 3]), 0, 1))).max()))
    rep = {"op": "keyRotations", "table": op["table"], "sha256": op["sha256"], "keys": done,
           "maxOffsetDeg": round(worst, 2)}
    if regridded:
        rep["regridded"] = regridded
    return rep


def key_translations_table(op: dict) -> tuple[dict | None, list[str]]:
    """(table, schema errors) of a keyTranslations op: a repo file under KEY_ROT_DIR pinned by its sha256, schema
    KEY_TR_SCHEMA, {clips: {clip: {bone: {times, delta}}}} with one [dx, dy, dz] (glTF local units) per time."""
    t = op.get("table")
    if not (isinstance(t, str) and t.replace("\\", "/").startswith(KEY_ROT_DIR + "/") and t.endswith(".json")
            and ".." not in t):
        return None, [f"table must be a repo-relative {KEY_ROT_DIR}/<name>.json path"]
    p = ROOT / t
    if not p.is_file():
        return None, [f"table {t} does not exist"]
    raw = p.read_bytes()
    if op.get("sha256") != sha(raw):
        return None, [f"sha256 is not the table's ({sha(raw)}): re-pin it after editing {t}"]
    try:
        tab = json.loads(raw.decode("utf-8"))
    except ValueError as e:
        return None, [f"table {t} is not JSON ({e})"]
    bad = [] if tab.get("schema") == KEY_TR_SCHEMA else [f"table schema must be {KEY_TR_SCHEMA}"]
    cl = tab.get("clips")
    if not (isinstance(cl, dict) and cl):
        return tab, bad + ["table clips must be a non-empty {clip: {bone: {times, delta}}} map"]
    for c, bones in cl.items():
        for b, ch in (bones.items() if isinstance(bones, dict) else []):
            if not (isinstance(ch, dict) and set(ch) == {"times", "delta"}):
                bad.append(f"{c} {b}: must be {{times, delta}}"); continue
            tt, d = np.asarray(ch["times"], float), np.asarray(ch["delta"], float)
            if tt.ndim != 1 or not len(tt) or d.shape != (len(tt), 3) or np.any(np.diff(tt) <= 0):
                bad.append(f"{c} {b}: times must be increasing with one [dx, dy, dz] per time")
    return tab, bad


def key_scales_table(op: dict) -> tuple[dict | None, list[str]]:
    """(table, schema errors) of a keyScales op: a repo file under KEY_ROT_DIR pinned by its sha256, schema
    KEY_SC_SCHEMA, {clips: {clip: {bone: {times, factor}}}} with one [sx, sy, sz] (bone-local axes; glTF bones run
    along local +y) per time, each within KEY_SC_RANGE."""
    t = op.get("table")
    if not (isinstance(t, str) and t.replace("\\", "/").startswith(KEY_ROT_DIR + "/") and t.endswith(".json")
            and ".." not in t):
        return None, [f"table must be a repo-relative {KEY_ROT_DIR}/<name>.json path"]
    p = ROOT / t
    if not p.is_file():
        return None, [f"table {t} does not exist"]
    raw = p.read_bytes()
    if op.get("sha256") != sha(raw):
        return None, [f"sha256 is not the table's ({sha(raw)}): re-pin it after editing {t}"]
    try:
        tab = json.loads(raw.decode("utf-8"))
    except ValueError as e:
        return None, [f"table {t} is not JSON ({e})"]
    bad = [] if tab.get("schema") == KEY_SC_SCHEMA else [f"table schema must be {KEY_SC_SCHEMA}"]
    cl = tab.get("clips")
    if not (isinstance(cl, dict) and cl):
        return tab, bad + ["table clips must be a non-empty {clip: {bone: {times, factor}}} map"]
    for c, bones in cl.items():
        for b, ch in (bones.items() if isinstance(bones, dict) else []):
            if not (isinstance(ch, dict) and set(ch) == {"times", "factor"}):
                bad.append(f"{c} {b}: must be {{times, factor}}"); continue
            tt, f = np.asarray(ch["times"], float), np.asarray(ch["factor"], float)
            if tt.ndim != 1 or not len(tt) or f.shape != (len(tt), 3) or np.any(np.diff(tt) <= 0):
                bad.append(f"{c} {b}: times must be increasing with one [sx, sy, sz] per time"); continue
            if f.min() < KEY_SC_RANGE[0] or f.max() > KEY_SC_RANGE[1]:
                bad.append(f"{c} {b}: factors must be within {KEY_SC_RANGE}")
    return tab, bad


def op_key_scales(g: Glb, op: dict) -> dict:
    """Multiply listed bones' scale keys by the table's per-time factors (bone-local axes). A channel whose key grid
    differs from the table's is resampled onto the table's grid (which must span the channel's first..last key, so
    the clip length cannot change). Children inherit the scale (a lengthened upper arm carries the forearm and hand
    out with it): the punch of a stub-armed body (lane C 2026-10-12 h3_air_elemental, arms thrust out of the cloud
    mass). Geometry and skin untouched; the CS re-bake and tear gate see the scaled poses."""
    tab, bad = key_scales_table(op)
    if bad:
        raise SystemExit(f"keyScales: {'; '.join(bad)}")
    done, lo, hi, regridded = {}, 1.0, 1.0, {}
    for clip, bones in tab["clips"].items():
        a = g.anim(clip)
        for bone, ch in bones.items():
            if bone not in g.names:
                raise SystemExit(f"keyScales: no node {bone!r}")
            node = g.names.index(bone)
            cs = [c for c in a["channels"] if c["target"]["node"] == node and c["target"]["path"] == "scale"]
            if len(cs) != 1:
                raise SystemExit(f"keyScales: {clip} has {len(cs)} scale channels on {bone} (needs one)")
            s = a["samplers"][cs[0]["sampler"]]
            it = s.get("interpolation", "LINEAR")
            if it not in ("LINEAR", "STEP"):
                raise SystemExit(f"keyScales: {clip} {bone} scale is {it}; LINEAR and STEP only")
            t = g.read(s["input"])[:, 0]
            v = g.read(s["output"]).astype(np.float64)
            tt, f = np.asarray(ch["times"], float), np.asarray(ch["factor"], float)
            if len(t) != len(tt) or np.abs(t - tt).max() > KEY_ROT_TIME_EPS:
                if not (abs(tt[0] - t[0]) <= KEY_ROT_TIME_EPS and abs(tt[-1] - t[-1]) <= KEY_ROT_TIME_EPS):
                    raise SystemExit(f"keyScales: {clip} {bone}: the table must span the channel's first..last key "
                                     f"({t[0]:.4f}..{t[-1]:.4f}) to regrid it")
                if it == "STEP":
                    v = v[np.clip(np.searchsorted(t, tt + KEY_ROT_TIME_EPS, side="right") - 1, 0, len(t) - 1)]
                else:
                    v = np.stack([np.interp(tt, t, v[:, k]) for k in range(3)], 1)
                t, it = tt, "LINEAR"
                regridded.setdefault(clip, []).append(bone)
            write_channels(g, a, t, {(node, "scale"): v * f}, it)
            done.setdefault(clip, {})[bone] = len(t)
            lo, hi = min(lo, float(f.min())), max(hi, float(f.max()))
    rep = {"op": "keyScales", "table": op["table"], "sha256": op["sha256"], "keys": done,
           "factorRange": [round(lo, 4), round(hi, 4)]}
    if regridded:
        rep["regridded"] = regridded
    return rep


def tracks_table(op: dict) -> tuple[dict | None, list[str]]:
    """(table, schema errors) of a setTracks op: a repo file under KEY_ROT_DIR pinned by its sha256, schema
    TRACKS_SCHEMA, {clips: {clip: {times, bones: {bone: {translation?, rotation?, scale?}}}}} with one value per time
    (rotation: unit quaternion xyzw; scale: per axis within KEY_SC_RANGE)."""
    t = op.get("table")
    if not (isinstance(t, str) and t.replace("\\", "/").startswith(KEY_ROT_DIR + "/") and t.endswith(".json")
            and ".." not in t):
        return None, [f"table must be a repo-relative {KEY_ROT_DIR}/<name>.json path"]
    p = ROOT / t
    if not p.is_file():
        return None, [f"table {t} does not exist"]
    raw = p.read_bytes()
    if op.get("sha256") != sha(raw):
        return None, [f"sha256 is not the table's ({sha(raw)}): re-pin it after editing {t}"]
    try:
        tab = json.loads(raw.decode("utf-8"))
    except ValueError as e:
        return None, [f"table {t} is not JSON ({e})"]
    bad = [] if tab.get("schema") == TRACKS_SCHEMA else [f"table schema must be {TRACKS_SCHEMA}"]
    cl = tab.get("clips")
    if not (isinstance(cl, dict) and cl):
        return tab, bad + ["table clips must be a non-empty {clip: {times, bones}} map"]
    for c, d in cl.items():
        if not (isinstance(d, dict) and set(d) == {"times", "bones"} and isinstance(d["bones"], dict) and d["bones"]):
            bad.append(f"{c}: must be {{times, bones: {{bone: {{translation?, rotation?, scale?}}}}}}"); continue
        tt = np.asarray(d["times"], float)
        if tt.ndim != 1 or not len(tt) or np.any(np.diff(tt) <= 0):
            bad.append(f"{c}: times must be increasing"); continue
        for b, tr in d["bones"].items():
            if not (isinstance(tr, dict) and tr and not set(tr) - set(TRACK_PATHS)):
                bad.append(f"{c} {b}: must hold translation / rotation / scale"); continue
            for path, v in tr.items():
                try:
                    v = np.asarray(v, float)
                except (TypeError, ValueError):
                    v = np.zeros(0)
                if v.shape != (len(tt), TRACK_PATHS[path]) or not np.isfinite(v).all():
                    bad.append(f"{c} {b} {path}: needs one finite {TRACK_PATHS[path]}-vector per time")
                elif path == "rotation" and np.abs(np.linalg.norm(v, axis=1) - 1.0).max() > 1e-3:
                    bad.append(f"{c} {b} rotation: quaternions must be unit length")
                elif path == "scale" and (v.min() < KEY_SC_RANGE[0] or v.max() > KEY_SC_RANGE[1]):
                    bad.append(f"{c} {b} scale: must be within {KEY_SC_RANGE}")
    return tab, bad


def op_set_tracks(g: Glb, op: dict) -> dict:
    """Replace listed bones' keys of whole clips with the table's (LINEAR, on the clip's own key grid: the table's
    times must equal it, so clip length, the master frame mapping and the CS targets' keys are unchanged). Bones and
    paths the table does not list keep their channels. The clip is authored offline on the shipped rig (flyer
    flights, 2026-11-09 h3_roc); the CS re-bake and the tear gate see the new poses."""
    tab, bad = tracks_table(op)
    if bad:
        raise SystemExit(f"setTracks: {'; '.join(bad)}")
    done = {}
    for clip, d in tab["clips"].items():
        a = g.anim(clip)
        t, grid = np.asarray(d["times"], float), g.key_grid(clip)
        if len(t) != len(grid) or np.abs(t - grid).max() > KEY_ROT_TIME_EPS:
            raise SystemExit(f"setTracks: {clip}: the table's {len(t)} times are not the clip's key grid "
                             f"({len(grid)} keys, {grid[0]:.4f}..{grid[-1]:.4f})")
        tg = {}
        for bone, tr in d["bones"].items():
            if bone not in g.names:
                raise SystemExit(f"setTracks: no node {bone!r}")
            for path, v in tr.items():
                v = np.asarray(v, float)
                tg[(g.names.index(bone), path)] = v / np.linalg.norm(v, axis=1, keepdims=True) if path == "rotation" else v
        write_channels(g, a, t, tg, "LINEAR")
        done[clip] = {"keys": len(t), "bones": len(d["bones"])}
    return {"op": "setTracks", "table": op["table"], "sha256": op["sha256"], "clips": done}


def op_key_translations(g: Glb, op: dict, height: float) -> dict:
    """Add the table's per-time translation deltas to listed bones' translation keys, linearly interpolated (held
    past the ends) onto the channel's own key grid. Used to carry a fitted root path across a rebuild whose
    build-time screen-offset fit moved (2026-10-07 h3_royal_griffin wing surgery). Geometry and skin untouched."""
    tab, bad = key_translations_table(op)
    if bad:
        raise SystemExit(f"keyTranslations: {'; '.join(bad)}")
    if "regrid" in op and not isinstance(op["regrid"], bool):
        raise SystemExit("keyTranslations: regrid must be true or false")
    done, worst, regridded = {}, 0.0, {}
    for clip, bones in tab["clips"].items():
        a = g.anim(clip)
        for bone, ch in bones.items():
            if bone not in g.names:
                raise SystemExit(f"keyTranslations: no node {bone!r}")
            node = g.names.index(bone)
            cs = [c for c in a["channels"] if c["target"]["node"] == node and c["target"]["path"] == "translation"]
            if len(cs) != 1:
                raise SystemExit(f"keyTranslations: {clip} has {len(cs)} translation channels on {bone} (needs one)")
            s = a["samplers"][cs[0]["sampler"]]
            it = s.get("interpolation", "LINEAR")
            if it not in ("LINEAR", "STEP"):
                raise SystemExit(f"keyTranslations: {clip} {bone} translation is {it}; LINEAR and STEP only")
            t = g.read(s["input"])[:, 0]
            v = g.read(s["output"]).astype(np.float64)
            tt, d = np.asarray(ch["times"], float), np.asarray(ch["delta"], float)
            if op.get("regrid") is True and (len(t) != len(tt) or np.abs(t - tt).max() > KEY_ROT_TIME_EPS):
                # regrid: a sparse channel (e.g. a 2-key static hold, whose mid-clip deltas would otherwise
                # interpolate away) is resampled onto the table's denser grid; the span must be the channel's own
                # first..last key so the clip length cannot change (2026-10-07 h3_royal_griffin wing lengthening)
                if not (abs(tt[0] - t[0]) <= KEY_ROT_TIME_EPS and abs(tt[-1] - t[-1]) <= KEY_ROT_TIME_EPS):
                    raise SystemExit(f"keyTranslations: {clip} {bone}: regrid needs the table to span the channel's "
                                     f"first..last key ({t[0]:.4f}..{t[-1]:.4f})")
                if it == "STEP":
                    j = np.clip(np.searchsorted(t, tt + KEY_ROT_TIME_EPS, side="right") - 1, 0, len(t) - 1)
                    v = v[j]
                else:
                    v = np.stack([np.interp(tt, t, v[:, k]) for k in range(3)], 1)
                t, it = tt, "LINEAR"
                regridded.setdefault(clip, []).append(bone)
            dd = np.stack([np.interp(t, tt, d[:, k]) for k in range(3)], 1)
            m = float(np.linalg.norm(dd, axis=1).max())
            if m > KEY_TR_MAX_OVER_H * height:
                raise SystemExit(f"keyTranslations: {clip} {bone}: a delta of {m:.3f} exceeds "
                                 f"{KEY_TR_MAX_OVER_H} x the body height")
            write_channels(g, a, t, {(node, "translation"): v + dd}, it)
            done.setdefault(clip, {})[bone] = len(t)
            worst = max(worst, m / height)
    rep = {"op": "keyTranslations", "table": op["table"], "sha256": op["sha256"], "keys": done,
           "maxDeltaOverHeight": round(worst, 4)}
    if regridded:
        rep["regridded"] = regridded
    return rep


def resample_rot(t: np.ndarray, r: np.ndarray, tt: np.ndarray, interpolation: str) -> np.ndarray:
    """Unit xyzw rotation keys r on grid t sampled at times tt (inside [t0, t1]) as the glTF sampler would: slerp
    between neighbouring keys for LINEAR, hold the previous key for STEP."""
    out = np.empty((len(tt), 4))
    for k, x in enumerate(tt):
        j = int(np.clip(np.searchsorted(t, x, side="right") - 1, 0, len(t) - 1))
        if interpolation == "STEP" or j == len(t) - 1 or t[j + 1] - t[j] <= 0:
            out[k] = r[j]; continue
        w = float(np.clip((x - t[j]) / (t[j + 1] - t[j]), 0.0, 1.0))
        a, b = r[j], r[j + 1]
        d = float(np.dot(a, b))
        if d < 0:
            b, d = -b, -d
        if d > 0.9995:
            q = a + w * (b - a)
        else:
            th = np.arccos(d)
            q = (np.sin((1 - w) * th) * a + np.sin(w * th) * b) / np.sin(th)
        out[k] = q / np.linalg.norm(q)
    return out


# ---------------------------------------------------------------------------------------------------- GLB access
class Body:
    """The skinned body primitive (the largest skinned mesh not carried by a *_Rubble node, as look and bake_cs use)."""

    def __init__(self, g: Glb):
        cand = [(i, n) for i, n in enumerate(g.nodes) if "mesh" in n and "skin" in n
                and not (n.get("name") or "").endswith("_Rubble")]
        if not cand:
            raise SystemExit("no skinned body mesh")
        prims = {i: g.json["meshes"][n["mesh"]]["primitives"] for i, n in cand}
        ni, node = max(cand, key=lambda t: g.json["accessors"][prims[t[0]][0]["attributes"]["POSITION"]]["count"])
        if len(prims[ni]) != 1:
            raise SystemExit(f"body mesh {node.get('name')} has {len(prims[ni])} primitives; the patch lane edits one")
        j = ni
        while j is not None:   # the body's axes are build_unit's only through identity nodes
            n = g.nodes[j]
            if "matrix" in n or any(not np.allclose(n.get(k, d), d) for k, d in
                                    (("translation", [0, 0, 0]), ("rotation", [0, 0, 0, 1]), ("scale", [1, 1, 1]))):
                raise SystemExit(f"node {n.get('name')} above the body mesh has a transform; the patch lane needs "
                                 "identity body and rig nodes (rest space = mesh space)")
            j = g.parent.get(j)
        self.node, self.mesh = ni, node["mesh"]
        self.prim = prims[ni][0]
        skin = g.json["skins"][node["skin"]]
        self.joints = skin["joints"]
        self.jnames = [g.names[j] for j in self.joints]
        self.ibm = g.read(skin["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1)
        at = self.prim["attributes"]
        self.V = g.read(at["POSITION"])
        self.J = g.read(at["JOINTS_0"]).astype(np.int64)
        self.W = g.read(at["WEIGHTS_0"])
        if "JOINTS_1" in at or "WEIGHTS_1" in at:
            raise SystemExit("body has a second influence set (JOINTS_1); the patch lane edits four influences")
        self.F = g.read(self.prim["indices"]).astype(np.int64).reshape(-1, 3)
        self.targets = [t["POSITION"] for t in self.prim.get("targets", [])]
        self.target_names = (g.json["meshes"][self.mesh].get("extras") or {}).get("targetNames") or []
        if self.targets and len(self.target_names) != len(self.targets):
            raise SystemExit("morph targets without matching mesh.extras.targetNames")
        self.H = float(self.V[:, 1].max() - self.V[:, 1].min())


def overwrite(g: Glb, ai: int, arr: np.ndarray, refs: dict) -> None:
    """Write arr into accessor ai's own bytes (same count, type, component type); refuses sparse / shared data."""
    a = g.json["accessors"][ai]
    if "sparse" in a or refs.get(ai, 0) != 1:
        raise SystemExit(f"accessor {ai} is sparse or shared ({refs.get(ai, 0)} references); refusing an in-place write")
    bv = g.json["bufferViews"][a["bufferView"]]
    if sum(1 for x in g.json["accessors"] if x.get("bufferView") == a["bufferView"]) != 1 or bv.get("byteStride"):
        raise SystemExit(f"accessor {ai} shares or strides its bufferView; refusing an in-place write")
    dt = {5126: "<f4", 5121: "u1", 5123: "<u2"}[a["componentType"]]
    w = {"SCALAR": 1, "VEC3": 3, "VEC4": 4}[a["type"]]
    data = np.ascontiguousarray(arr, dtype=dt).reshape(a["count"], w)
    off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    b = data.tobytes()
    g.bin[off:off + len(b)] = b
    if "min" in a or "max" in a or a["type"] == "VEC3":
        a["min"] = [float(x) for x in data.min(0)]
        a["max"] = [float(x) for x in data.max(0)]


def accessor_refs(g: Glb) -> dict:
    refs: dict = {}

    def add(i):
        refs[i] = refs.get(i, 0) + 1
    for m in g.json["meshes"]:
        for p in m["primitives"]:
            for v in p["attributes"].values():
                add(v)
            if "indices" in p:
                add(p["indices"])
            for t in p.get("targets", []):
                for v in t.values():
                    add(v)
    for a in g.json.get("animations", []):
        for s in a["samplers"]:
            add(s["input"])
            add(s["output"])
    for s in g.json.get("skins", []):
        if "inverseBindMatrices" in s:
            add(s["inverseBindMatrices"])
    return refs


# ---------------------------------------------------------------------------------------------------- ops
def blender_axes(V: np.ndarray) -> np.ndarray:
    return np.stack([V[:, 0], -V[:, 2], V[:, 1]], 1)


def op_diffuse_weights(body: Body, op: dict, J: np.ndarray, W: np.ndarray) -> tuple[np.ndarray, np.ndarray, dict]:
    """Laplacian diffusion of the skin weights across a joint: every vertex weighted (> 0.01) to one of `bones` moves
    `alpha` of the way to its mesh neighbours' mean weights, `iterations` times; vertices at one rest position (UV-seam
    copies, one weld group) keep identical weights. Top 4 influences, renormalised. Spreads a hard weight boundary
    (a fold or crease that tears or pinches) over its neighbourhood; the bone set never grows beyond the neighbours'."""
    names = body.jnames
    sel = sorted({i for i, n in enumerate(names) for pat in op["bones"] if fnmatch.fnmatchcase(n, pat)})
    if len(sel) == 0:
        raise SystemExit(f"diffuseWeights: bones {op['bones']} match no joint of the skin")
    nj = len(names); nv = len(J)
    D = np.zeros((nv, nj))
    np.add.at(D, (np.repeat(np.arange(nv), J.shape[1]), J.ravel()), W.ravel())
    # weld groups at bake_cs's own key precision (rest position to 5 decimals): a finer key leaves seam copies that the
    # gate's Weld treats as one group in different groups here, and a copy left out of `free` would split the weld
    _, grp = np.unique(np.round(body.V, 5), axis=0, return_inverse=True)
    grp = grp.ravel(); ng = grp.max() + 1
    gsel = np.zeros(ng, bool); gsel[grp[D[:, sel].max(1) > 0.01]] = True
    free = gsel[grp]
    # adjacency over weld groups (seam copies share neighbours)
    E = np.concatenate([body.F[:, [0, 1]], body.F[:, [1, 2]], body.F[:, [2, 0]]])
    ge = np.unique(np.sort(grp[E], 1), axis=0); ge = ge[ge[:, 0] != ge[:, 1]]
    G = np.zeros((ng, nj)); cnt = np.bincount(grp, minlength=ng)[:, None]
    np.add.at(G, grp, D); G /= cnt
    gfree = np.zeros(ng, bool); gfree[grp[free]] = True
    a = float(op["alpha"])
    if "region" in op:
        # optional spatial limit (moveWeights ramps, Blender body axes): only weld groups inside it move, by alpha x ramp,
        # and only groups weighted to `bones` alone take part (free or as neighbours), so the diffusion never averages
        # across a rip into an arm, a bound prop island or any other bone left out of `bones`
        Pb = blender_axes(body.V); ax = {"x": 0, "y": 1, "z": 2}; ramp = np.ones(nv)
        for r in op["region"]:
            c = Pb[:, ax[r["axis"]]]
            ramp *= np.clip((c - r["above"]) / r["ramp"], 0, 1) if "above" in r else np.clip((r["below"] - c) / r["ramp"], 0, 1)
        gr = np.zeros(ng); np.maximum.at(gr, grp, ramp)
        Gmax = np.zeros((ng, nj)); np.maximum.at(Gmax, grp, D)
        other = [j for j in range(nj) if j not in sel]
        pure = Gmax[:, other].max(1) < 0.01 if other else np.ones(ng, bool)
        gfree &= (gr > 0) & pure
        ge = ge[pure[ge[:, 0]] & pure[ge[:, 1]]]
        free = gfree[grp]
        a = a * gr[:, None]
    deg = np.bincount(ge.ravel(), minlength=ng)[:, None]
    for _ in range(int(op["iterations"])):
        S = np.zeros_like(G); np.add.at(S, ge[:, 0], G[ge[:, 1]]); np.add.at(S, ge[:, 1], G[ge[:, 0]])
        M = np.where(deg > 0, S / np.maximum(deg, 1), G)
        G = np.where(gfree[:, None], (1 - a) * G + a * M, G)
    D2 = G[grp]
    J2, W2 = J.copy(), W.copy()
    idx = np.flatnonzero(free)
    top = np.argsort(-D2[idx], 1)[:, :J.shape[1]]
    wt = np.take_along_axis(D2[idx], top, 1); wt[wt < 1e-6] = 0
    wt /= wt.sum(1, keepdims=True)
    k = top.shape[1]                                     # fewer joints than influences: pad the tail with zeros
    J2[idx] = 0; W2[idx] = 0
    J2[idx, :k] = np.where(wt > 0, top, 0); W2[idx, :k] = wt
    moved = float(np.abs(D2[idx] - D[idx]).sum(1).max()) / 2 if len(idx) else 0.0
    return J2, W2, {"op": "diffuseWeights", "bones": [names[i] for i in sel], "vertices": int(len(idx)),
                    "maxWeightMoved": round(moved, 4), "note": op.get("note", "")}


def weight_table(op: dict) -> tuple[dict | None, list[str]]:
    """(table, schema errors) of a setWeights op: a repo file under KEY_ROT_DIR pinned by its sha256, schema
    homm3_glb_patch_weight_table.v1 {vertexCount, vertices: {index: {bone: weight}}}: at most four bones a vertex,
    weights in (0, 1] summing to 1."""
    t = op.get("table")
    if not (isinstance(t, str) and t.replace("\\", "/").startswith(KEY_ROT_DIR + "/") and t.endswith(".json")
            and ".." not in t):
        return None, [f"table must be a repo-relative {KEY_ROT_DIR}/<name>.json path"]
    p = ROOT / t
    if not p.is_file():
        return None, [f"table {t} does not exist"]
    raw = p.read_bytes()
    if op.get("sha256") != sha(raw):
        return None, [f"sha256 is not the table's ({sha(raw)}): re-pin it after editing {t}"]
    try:
        tab = json.loads(raw.decode("utf-8"))
    except ValueError as e:
        return None, [f"table {t} is not JSON ({e})"]
    bad = []
    if tab.get("schema") != WEIGHT_TABLE_SCHEMA:
        bad.append(f"table schema must be {WEIGHT_TABLE_SCHEMA}")
    if not isinstance(tab.get("vertexCount"), int):
        bad.append("table vertexCount must be the body's vertex count")
    vs = tab.get("vertices")
    if not (isinstance(vs, dict) and vs):
        return tab, bad + ["table vertices must be a non-empty {index: {bone: weight}} map"]
    for v, bw in vs.items():
        if not (v.isdigit() and isinstance(bw, dict) and 0 < len(bw) <= 4
                and all(isinstance(x, (int, float)) and 0 < x <= 1 for x in bw.values())
                and abs(sum(bw.values()) - 1) < 1e-3):
            bad.append(f"vertex {v}: must be 1-4 bones with weights in (0, 1] summing to 1")
            break
    return tab, bad


def op_set_weights(body: Body, op: dict, J: np.ndarray, W: np.ndarray) -> tuple[np.ndarray, np.ndarray, dict]:
    """Replace the listed vertices' skin weights with the table's (a per-vertex re-solve made offline, e.g. the
    shoulder/armpit of a raised-arm pose); every other vertex keeps its weights."""
    tab, bad = weight_table(op)
    if bad:
        raise SystemExit(f"setWeights: {'; '.join(bad)}")
    if tab["vertexCount"] != len(body.V):
        raise SystemExit(f"setWeights: the table is for {tab['vertexCount']} vertices, the body has {len(body.V)}")
    names = body.jnames
    J2, W2 = J.copy(), W.copy()
    for v, bw in tab["vertices"].items():
        v = int(v)
        if v >= len(J):
            raise SystemExit(f"setWeights: vertex {v} is out of range")
        miss = [b for b in bw if b not in names]
        if miss:
            raise SystemExit(f"setWeights: bones {miss} are not joints of the skin")
        live = sorted(bw.items(), key=lambda t: -t[1])
        s = sum(x for _, x in live)
        J2[v] = 0; W2[v] = 0.0
        for k, (b, x) in enumerate(live):
            J2[v, k], W2[v, k] = names.index(b), x / s
    return J2, W2, {"op": "setWeights", "table": op["table"], "sha256": op["sha256"],
                    "vertices": len(tab["vertices"]), "note": op.get("note", "")}


def pinned_table(op: dict, schema: str) -> tuple[dict | None, list[str]]:
    """(table, errors) of an op's sha256-pinned repo table under KEY_ROT_DIR with the given schema."""
    t = op.get("table")
    if not (isinstance(t, str) and t.replace("\\", "/").startswith(KEY_ROT_DIR + "/") and t.endswith(".json")
            and ".." not in t):
        return None, [f"table must be a repo-relative {KEY_ROT_DIR}/<name>.json path"]
    p = ROOT / t
    if not p.is_file():
        return None, [f"table {t} does not exist"]
    raw = p.read_bytes()
    if op.get("sha256") != sha(raw):
        return None, [f"sha256 is not the table's ({sha(raw)}): re-pin it after editing {t}"]
    try:
        tab = json.loads(raw.decode("utf-8"))
    except ValueError as e:
        return None, [f"table {t} is not JSON ({e})"]
    if not isinstance(tab, dict) or tab.get("schema") != schema:
        return None, [f"table schema must be {schema}"]
    return tab, []


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and bool(np.isfinite(v))


def joints_table(op: dict) -> tuple[dict | None, list[str]]:
    """(table, schema errors) of an addJoints op: JOINTS_SCHEMA {jointCount, joints: [{name, parent, head}]}; a parent
    is a joint of the skin or an earlier joint of the table (checked against the skin by the op)."""
    tab, bad = pinned_table(op, JOINTS_SCHEMA)
    if tab is None:
        return tab, bad
    return tab, joints_table_errors(tab)


def joints_table_errors(tab: dict) -> list[str]:
    bad = []
    extra = set(tab) - {"schema", "unit", "note", "jointCount", "joints"}
    if extra:
        bad.append(f"unknown table keys {sorted(extra)}")
    if not (isinstance(tab.get("jointCount"), int) and not isinstance(tab["jointCount"], bool) and tab["jointCount"] > 0):
        bad.append("table jointCount must be the skin's joint count the table was authored on")
    js = tab.get("joints")
    if not (isinstance(js, list) and js):
        return bad + ["table joints must be a non-empty list of {name, parent, head}"]
    seen = set()
    for k, j in enumerate(js):
        if not (isinstance(j, dict) and set(j) == {"name", "parent", "head"} and isinstance(j["name"], str)
                and j["name"].strip() == j["name"] and j["name"] and isinstance(j["parent"], str) and j["parent"]
                and isinstance(j["head"], list) and len(j["head"]) == 3 and all(_num(x) for x in j["head"])):
            bad.append(f"joints[{k}]: must be {{name, parent, head: [x, y, z]}}")
            continue
        if j["name"] in seen:
            bad.append(f"joints[{k}]: duplicate name {j['name']!r}")
        if j["parent"] == j["name"]:
            bad.append(f"joints[{k}]: {j['name']!r} is its own parent")
        seen.add(j["name"])
    return bad


def face_cut_table(op: dict) -> tuple[dict | None, list[str]]:
    """(table, schema errors) of a cutFaces op: FACE_CUT_SCHEMA {faceCount, indexSha256, faces}: strictly increasing
    row numbers of the export's index buffer, which indexSha256 pins."""
    tab, bad = pinned_table(op, FACE_CUT_SCHEMA)
    if tab is None:
        return tab, bad
    return tab, face_cut_table_errors(tab)


def face_cut_table_errors(tab: dict) -> list[str]:
    bad = []
    extra = set(tab) - {"schema", "unit", "note", "faceCount", "indexSha256", "faces"}
    if extra:
        bad.append(f"unknown table keys {sorted(extra)}")
    n = tab.get("faceCount")
    if not (isinstance(n, int) and not isinstance(n, bool) and n > 0):
        bad.append("table faceCount must be the body's triangle count")
        n = None
    if not (isinstance(tab.get("indexSha256"), str) and len(tab["indexSha256"]) == 64):
        bad.append("table indexSha256 must be the sha256 of the export's index buffer bytes")
    fs = tab.get("faces")
    if not (isinstance(fs, list) and fs and all(isinstance(x, int) and not isinstance(x, bool) for x in fs)):
        return bad + ["table faces must be a non-empty list of face indices"]
    if any(b <= a for a, b in zip(fs, fs[1:])) or fs[0] < 0:
        bad.append("table faces must be strictly increasing, from 0")
    if n is not None:
        if fs[-1] >= n:
            bad.append(f"table faces reach {fs[-1]}, past faceCount {n}")
        if len(fs) > CUT_MAX_SHARE * n:
            bad.append(f"table cuts {len(fs)} of {n} faces, more than {CUT_MAX_SHARE} of the body (a remesh, not a cut)")
    return bad


def index_bytes(g: Glb, ai: int) -> bytes:
    """The raw little-endian bytes of an index accessor (tightly packed)."""
    a = g.json["accessors"][ai]
    bv = g.json["bufferViews"][a["bufferView"]]
    if "sparse" in a or bv.get("byteStride"):
        raise SystemExit(f"index accessor {ai} is sparse or strided")
    size = {5121: 1, 5123: 2, 5125: 4}[a["componentType"]]
    off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    return bytes(g.bin[off:off + a["count"] * size])


def op_add_joints(g: Glb, body: "Body", op: dict, tab: dict | None = None) -> dict:
    """Append the table's joints to the rig (see the module docstring). Edits g in place: nodes, the skin's joint list
    and inverse bind accessor, and a rest-TRS hold in every animation; the caller rebuilds Body(g)."""
    if tab is None:
        tab, bad = joints_table(op)
        if bad:
            raise SystemExit(f"addJoints: {'; '.join(bad)}")
    if tab["jointCount"] != len(body.joints):
        raise SystemExit(f"addJoints: the table was authored on a {tab['jointCount']}-joint skin, this skin has "
                         f"{len(body.joints)} (another export, or the joints were already added)")
    if len(g.json.get("skins", [])) != 1:
        raise SystemExit(f"addJoints: the GLB has {len(g.json.get('skins', []))} skins; the op edits a single-skin export")
    if len(body.joints) + len(tab["joints"]) > MAX_SKIN_JOINTS:
        raise SystemExit(f"addJoints: {len(body.joints)} + {len(tab['joints'])} joints exceed {MAX_SKIN_JOINTS}")
    skin = g.json["skins"][g.nodes[body.node]["skin"]]
    lo, hi = body.V.min(0) - JOINT_HEAD_MARGIN * body.H, body.V.max(0) + JOINT_HEAD_MARGIN * body.H
    bind = {n: np.linalg.inv(m) for n, m in zip(body.jnames, body.ibm)}      # joint bind world matrices
    node_of = dict(zip(body.jnames, body.joints))
    new_ibm, added = [], []
    for j in tab["joints"]:
        name, par = j["name"], j["parent"]
        if name in g.names:
            raise SystemExit(f"addJoints: a node named {name!r} already exists")
        if par not in bind:
            raise SystemExit(f"addJoints: parent {par!r} of {name!r} is neither a skin joint nor an earlier new joint")
        head = np.asarray(j["head"], float)
        if np.any(head < lo) or np.any(head > hi):
            raise SystemExit(f"addJoints: head of {name!r} {head.tolist()} is outside the body's rest bounds "
                             f"(+- {JOINT_HEAD_MARGIN} x height); rest-space glTF coordinates are expected")
        Gp = bind[par]
        R = Gp[:3, :3]
        if np.abs(R.T @ R - np.eye(3)).max() > 1e-4 or np.linalg.det(R) < 0:
            raise SystemExit(f"addJoints: parent {par!r} has a scaled or sheared bind matrix; the new joint's rest "
                             "TRS would not be a rigid transform")
        Gk = np.eye(4)
        Gk[:3, 3] = head
        L = np.linalg.inv(Gp) @ Gk
        q = G.mat_q(L[:3, :3])
        q = q / np.linalg.norm(q)
        node = {"name": name, "translation": [float(np.float32(x)) for x in L[:3, 3]],
                "rotation": [float(np.float32(x)) for x in (q if q[3] >= 0 else -q)]}
        g.nodes.append(node)
        ni = len(g.nodes) - 1
        g.names.append(name)
        g.nodes[node_of[par]].setdefault("children", []).append(ni)
        g.parent[ni] = node_of[par]
        skin["joints"].append(ni)
        node_of[name], bind[name] = ni, Gk
        new_ibm.append(np.linalg.inv(Gk))
        added.append(ni)
    ibm = np.concatenate([body.ibm, np.stack(new_ibm)])
    skin["inverseBindMatrices"] = g.append_accessor(ibm.transpose(0, 2, 1).reshape(-1, 16), "MAT4")
    # a rest-TRS hold in every clip, as the export keys a static bone: 2-key STEP translation / rotation / scale over
    # the clip's own first..last key, one sampler per channel (idle retime refuses shared samplers)
    held = 0
    for a in g.json.get("animations", []):
        ends = [g.read(s["input"])[[0, -1], 0] for s in a["samplers"]]
        if not ends:
            raise SystemExit(f"addJoints: animation {a.get('name')} has no key span to hold the new joints over")
        # the float32 first / last key MOST samplers carry, not the min / max: an earlier regrid op can leave a few
        # channels a float rounding off the export's key (0.083333 next to 0.08333334), and a hold keyed on that
        # stray time puts a near-duplicate key into the clip's key union (2026-11-10 h3_griffin: the ground stage
        # then wrote an 11-key Hips track into a x3-densified 10-key clip and the freeze gate read it as resampled)
        t0, t1 = (float(vals[np.argmax(n)]) for vals, n in
                  (np.unique(np.array([e[k] for e in ends], np.float32), return_counts=True) for k in (0, 1)))
        if t1 <= t0:
            raise SystemExit(f"addJoints: animation {a.get('name')} has no key span to hold the new joints over")
        tin = g.append_accessor(np.array([[t0], [t1]], np.float32), "SCALAR")
        for ni in added:
            n = g.nodes[ni]
            for path, v, typ in (("translation", n["translation"], "VEC3"), ("rotation", n["rotation"], "VEC4"),
                                 ("scale", [1.0, 1.0, 1.0], "VEC3")):
                out = g.append_accessor(np.array([v, v], np.float32), typ)
                a["samplers"].append({"input": tin, "output": out, "interpolation": "STEP"})
                a["channels"].append({"sampler": len(a["samplers"]) - 1, "target": {"node": ni, "path": path}})
                held += 1
    # the bake never saw these joints: a vertex re-skinned to them (setWeights) gets no Corrective Smooth, by the
    # bake's own exclusion rule (correctiveSmooth.excludeBones: the corrective is scaled by 1 - the weight on the
    # listed bones). CS on a thin ribbon that a new chain bends away from its rest curl collapses it (2026-11-10
    # h3_demon: the re-baked Move targets cut the tail in two; tools/homm3_def_retarget/ext/rig_chain.py pairs every
    # chain it builds with the same exclusion). cs_rebake's new side and cs_rekey downstream read this record.
    excluded = []
    bake = (g.json.get("asset", {}).get("extras") or {}).get(CS.BAKE_STAMP)
    if isinstance(bake, dict):
        excluded = [j["name"] for j in tab["joints"]]
        bake["excludeBones"] = list(bake.get("excludeBones") or []) + excluded
    return {"op": "addJoints", "table": op["table"], "sha256": op["sha256"], "jointCount": [tab["jointCount"], len(ibm)],
            "joints": [[j["name"], j["parent"]] for j in tab["joints"]], "heldChannels": held,
            "correctiveExcludeBonesAdded": excluded, "note": op.get("note", "")}


def op_cut_faces(g: Glb, body: "Body", op: dict, tab: dict | None = None) -> dict:
    """Drop the table's triangles from the body's index buffer, in place (the accessor and its bufferView shrink; the
    freed tail bytes are zeroed). The caller rebuilds Body(g)."""
    if tab is None:
        tab, bad = face_cut_table(op)
        if bad:
            raise SystemExit(f"cutFaces: {'; '.join(bad)}")
    if body.prim.get("mode", 4) != 4:
        raise SystemExit("cutFaces: the body primitive is not a triangle list")
    ai = body.prim["indices"]
    a = g.json["accessors"][ai]
    if tab["faceCount"] != len(body.F):
        raise SystemExit(f"cutFaces: the table is for {tab['faceCount']} faces, the body has {len(body.F)}")
    raw = index_bytes(g, ai)
    if sha(raw) != tab["indexSha256"]:
        raise SystemExit(f"cutFaces: the body's index buffer ({sha(raw)}) is not the one the table pins "
                         f"({tab['indexSha256']}): another export; rebuild the table on this one")
    if accessor_refs(g).get(ai, 0) != 1 or sum(1 for x in g.json["accessors"] if x.get("bufferView") == a["bufferView"]) != 1:
        raise SystemExit("cutFaces: the index accessor or its bufferView is shared; refusing an in-place cut")
    keep = np.ones(len(body.F), bool)
    keep[np.asarray(tab["faces"], np.int64)] = False
    F1 = body.F[keep]
    used = np.zeros(len(body.V), bool)
    used[body.F.ravel()] = True
    orphan = used.copy()
    orphan[F1.ravel()] = False
    # vertices only the cut faces used stay in the buffers (no vertex is ever removed or renumbered: the morph
    # targets, the look's texture fit and every weight table index them). They are still skinned, so the ground /
    # bounds stages see the same point cloud as before the cut; they are simply never drawn. Reported, not refused.
    dt = {5121: "u1", 5123: "<u2", 5125: "<u4"}[a["componentType"]]
    data = np.ascontiguousarray(F1.reshape(-1), dtype=dt).tobytes()
    bv = g.json["bufferViews"][a["bufferView"]]
    off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    g.bin[off:off + len(raw)] = data + b"\0" * (len(raw) - len(data))
    a["count"] = int(F1.size)
    bv["byteLength"] = a.get("byteOffset", 0) + len(data)
    if "min" in a or "max" in a:
        a["min"], a["max"] = [int(F1.min())], [int(F1.max())]
    return {"op": "cutFaces", "table": op["table"], "sha256": op["sha256"], "faces": [len(body.F), len(F1)],
            "facesCut": int(len(body.F) - len(F1)), "orphanVertices": int(orphan.sum()), "indexSha256": [tab["indexSha256"], sha(data)],
            "note": op.get("note", "")}


def vertex_data_sha(data: bytes) -> str:
    """sha256 over the body primitive's POSITION, NORMAL and TEXCOORD_0 bytes (the per-vertex geometry a cut keeps)."""
    sys.path.insert(0, str(ROOT / "tools/homm3_unit_look"))
    import glbpatch as LG  # noqa: E402
    lg = LG.Glb(data)
    h = hashlib.sha256()
    for p in lg.json["meshes"][lg.body_mesh_index()]["primitives"]:
        for k in ("POSITION", "NORMAL", "TEXCOORD_0"):
            if k in p["attributes"]:
                h.update(k.encode() + lg.accessor_bytes(p["attributes"][k]))
    return h.hexdigest()


def declared_cut_errors(delivered: bytes, base: bytes) -> list[str]:
    """Why `delivered` is NOT `base` with a declared cutFaces ([] = it is): the delivered GLB's patch stamp names
    `base` as its source and declares a face cut, the body's POSITION / NORMAL / TEXCOORD_0 bytes are the base's, and
    the delivered triangles are the base's rows in order minus exactly the stamped number of faces. The look's
    geometry gate (tools/homm3_unit_look/look.py stage_apply) accepts an index change only through this."""
    st = Glb(delivered).json.get("asset", {}).get("extras", {}).get(STAMP)
    topo = (st or {}).get("topology") if isinstance(st, dict) else None
    if not (isinstance(topo, dict) and isinstance(topo.get("facesCut"), int) and topo["facesCut"] > 0):
        return [f"the GLB's {STAMP} stamp declares no face cut"]
    if st.get("sourceGlbSha256") != sha(base):
        return [f"the {STAMP} stamp's source is not the retained base"]
    bad = []
    if vertex_data_sha(delivered) != vertex_data_sha(base):
        bad.append("the body's POSITION / NORMAL / TEXCOORD_0 bytes differ from the base's")
    F0, F1 = Body(Glb(base)).F, Body(Glb(delivered)).F
    if len(F0) - len(F1) != topo["facesCut"]:
        bad.append(f"{len(F0) - len(F1)} faces are gone, the stamp declares {topo['facesCut']}")
    else:
        i, n0 = 0, len(F0)                       # F1 must be an in-order subsequence of F0's rows
        for row in F1:
            while i < n0 and not np.array_equal(F0[i], row):
                i += 1
            if i == n0:
                bad.append("the delivered triangles are not the base's rows in order")
                break
            i += 1
    return bad


def op_move_weights(body: Body, op: dict, J: np.ndarray, W: np.ndarray) -> tuple[np.ndarray, np.ndarray, dict]:
    names = body.jnames
    src = sorted({i for i, n in enumerate(names) for pat in op["from"] if fnmatch.fnmatchcase(n, pat)})
    unmatched = [pat for pat in op["from"] if not any(fnmatch.fnmatchcase(n, pat) for n in names)]
    if unmatched:
        raise SystemExit(f"moveWeights: 'from' {unmatched} match no joint of the skin")
    if op["to"] not in names:
        raise SystemExit(f"moveWeights: 'to' {op['to']!r} is not a joint of the skin")
    to = names.index(op["to"])
    if to in src:
        raise SystemExit("moveWeights: 'to' is one of the 'from' bones")
    P = blender_axes(body.V)
    ax = {"x": 0, "y": 1, "z": 2}
    alpha = np.ones(len(P))
    for r in op["region"]:
        c = P[:, ax[r["axis"]]]
        alpha *= np.clip((c - r["above"]) / r["ramp"], 0, 1) if "above" in r else np.clip((r["below"] - c) / r["ramp"], 0, 1)
    alpha *= 1.0 - float(op.get("keep", 0.0))
    if op.get("onlyWith"):
        ow = op["onlyWith"]
        sel = [i for i, n in enumerate(names) for pat in ow["bones"] if fnmatch.fnmatchcase(n, pat)]
        if not sel:
            raise SystemExit(f"moveWeights: onlyWith bones {ow['bones']} match no joint of the skin")
        have = (np.isin(J, sel) * W).sum(1)
        alpha *= have >= float(ow["atLeast"])
    J2, W2 = J.copy(), W.copy()
    moved, total, capped = 0, 0.0, 0
    srcset = set(src)
    for v in np.flatnonzero(alpha > 0):
        w = {}
        for j, x in zip(J[v], W[v]):
            if x > 0:
                w[int(j)] = w.get(int(j), 0.0) + float(x)
        take = 0.0
        for j in list(w):
            if j in srcset:
                m = w[j] * alpha[v]
                w[j] -= m
                take += m
        if take <= 1e-6:
            continue
        w[to] = w.get(to, 0.0) + take
        live = sorted(((j, x) for j, x in w.items() if x > 1e-6), key=lambda t: -t[1])
        if len(live) > 4:
            capped += 1
            live = live[:4]
        s = sum(x for _, x in live)
        J2[v] = 0
        W2[v] = 0.0
        for k, (j, x) in enumerate(live):
            J2[v, k], W2[v, k] = j, x / s
        moved += 1
        total += take
    if moved == 0:
        raise SystemExit(f"moveWeights: the region moves no weight (from {op['from']}); the op would be a no-op")
    return J2, W2, {"op": "moveWeights", "vertices": moved, "weightMoved": round(total, 3), "influenceCapped": capped,
                    "regionVertices": int((alpha > 0).sum()), "to": op["to"], "from": [names[i] for i in src]}


def op_rotate_track(g: Glb, op: dict) -> dict:
    if op["bone"] not in g.names:
        raise SystemExit(f"rotateTrack: no node {op['bone']!r}")
    node = g.names.index(op["bone"])
    ax = np.asarray(op["axis"], float)
    ax /= np.linalg.norm(ax)
    h = np.radians(op["deg"]) / 2
    q = np.r_[ax * np.sin(h), np.cos(h)]
    done = {}
    for clip in op["clips"]:
        a = g.anim(clip)
        ch = [c for c in a["channels"] if c["target"]["node"] == node and c["target"]["path"] == "rotation"]
        if len(ch) != 1:
            raise SystemExit(f"rotateTrack: {clip} has {len(ch)} rotation channels on {op['bone']} (needs exactly one)")
        s = a["samplers"][ch[0]["sampler"]]
        it = s.get("interpolation", "LINEAR")
        if it not in ("LINEAR", "STEP"):
            raise SystemExit(f"rotateTrack: {clip} {op['bone']} rotation is {it}; LINEAR and STEP only")
        t = g.read(s["input"])[:, 0]
        r = g.read(s["output"])
        r = r / np.linalg.norm(r, axis=1, keepdims=True)
        new = qmul(r, q)
        write_channels(g, a, t, {(node, "rotation"): new}, it)
        done[clip] = len(t)
    return {"op": "rotateTrack", "bone": op["bone"], "deg": op["deg"], "axis": [float(x) for x in ax], "keys": done}


def sit_weight(shape: str, x: np.ndarray) -> np.ndarray:
    """The quadrupedSit ease shapes (tools/homm3_def_retarget/ext/rampart_quadruped_sit.py) over clip phase x."""
    return {"full": np.ones_like(x), "easeOut": 0.5 + 0.5 * np.cos(np.pi * x), "easeIn": 0.5 - 0.5 * np.cos(np.pi * x),
            "bracket": 0.5 + 0.5 * np.cos(2 * np.pi * x)}[shape]


def axis_rot(deg: float) -> np.ndarray:
    """Rotation by deg about the world lateral axis (glTF +x; positive turns +y toward +z, the unit's front)."""
    a = np.radians(deg)
    c, s_ = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0], [0, c, -s_], [0, s_, c]])


def rot_between(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    if c < -0.999999:
        raise SystemExit("sitRepose: a leg bone would flip 180 deg; reduce pitch / drop")
    K = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + K + K @ K / (1 + c)


def local_q(parent_world: np.ndarray, world: np.ndarray) -> np.ndarray:
    L = np.linalg.inv(parent_world) @ world
    return G.mat_q(L[:3, :3] / np.linalg.norm(L[:3, :3], axis=0))


def two_bone(H1, H0, K0, A0):
    """Knee and ankle of a hip(H1) -> knee -> ankle chain with the original lengths, reaching back to the original
    ankle A0, the knee on the original knee's side of the hip -> ankle line."""
    l1, l2 = np.linalg.norm(K0 - H0), np.linalg.norm(A0 - K0)
    d = A0 - H1
    dist = max(1e-6, min(np.linalg.norm(d), 0.999 * (l1 + l2)))
    u = d / np.linalg.norm(d)
    kh = K0 - H0
    kp = kh - u * np.dot(kh, u)
    kp /= max(np.linalg.norm(kp), 1e-9)
    aa = (l1 * l1 - l2 * l2 + dist * dist) / (2 * dist)
    return H1 + u * aa + kp * np.sqrt(max(l1 * l1 - aa * aa, 0.0)), H1 + u * dist


def two_bone_to(H, l1, l2, T, hint):
    """Knee and ankle of a two-bone chain from H with lengths l1, l2 reaching toward T (clamped to 0.999 of full
    reach), the knee on the `hint` side of the H -> T line."""
    d = T - H
    dist = max(1e-6, min(np.linalg.norm(d), 0.999 * (l1 + l2)))
    u = d / np.linalg.norm(d)
    kp = hint - u * np.dot(hint, u)
    if np.linalg.norm(kp) < 1e-9:
        raise SystemExit("sitRepose: foreleg bend hint is parallel to the leg")
    kp /= np.linalg.norm(kp)
    aa = (l1 * l1 - l2 * l2 + dist * dist) / (2 * dist)
    return H + u * aa + kp * np.sqrt(max(l1 * l1 - aa * aa, 0.0)), H + u * dist


def q_mat(q: np.ndarray) -> np.ndarray:
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def blend_rot(A: np.ndarray, B: np.ndarray, t: float) -> np.ndarray:
    """Rotation blended from A to B by t (3x3 rotations; normalised quaternion lerp)."""
    qa, qb = G.mat_q(A), G.mat_q(B)
    if np.dot(qa, qb) < 0:
        qb = -qb
    q = qa * (1 - t) + qb * t
    return q_mat(q / np.linalg.norm(q))


def unit_cols(M: np.ndarray) -> np.ndarray:
    return M / np.linalg.norm(M, axis=0)


def op_sit_repose(g: Glb, op: dict, height: float, body=None) -> dict:
    nm = g.names
    hips, legs = op.get("hips", "Hips"), op.get("legs", SIT_LEGS)
    turns = [(t["bone"], float(t["deg"])) for t in op.get("turns", [])]
    for b in [hips] + [b for c in legs for b in c] + [t for t, _ in turns]:
        if b not in nm:
            raise SystemExit(f"sitRepose: no node {b!r}")
    hi = nm.index(hips)
    par = g.parent.get(hi)
    if par is None:
        raise SystemExit(f"sitRepose: {hips} has no parent")
    for c in legs:
        iu, il, if_ = (nm.index(b) for b in c)
        if g.parent.get(iu) != hi or g.parent.get(il) != iu or g.parent.get(if_) != il:
            raise SystemExit(f"sitRepose: leg {c} is not a {hips} -> upper -> lower -> foot chain")
    anc = {}
    for b, _ in turns:   # every turned bone hangs under the hips and rides its nearest re-posed ancestor
        j, chain = nm.index(b), []
        while j is not None and j != hi:
            j = g.parent.get(j)
            chain.append(j)
        if j != hi:
            raise SystemExit(f"sitRepose: turn bone {b} is not under {hips}")
        anc[b] = chain
    fore = op.get("foreLegs")
    fchains, bind = [], {}
    if fore:
        if body is None:
            raise SystemExit("sitRepose: foreLegs needs the skinned body's bind pose")
        bw = {n: np.linalg.inv(m) for n, m in zip(body.jnames, body.ibm)}
        for c in fore["chains"]:
            for b in c:
                if b not in nm or b not in bw:
                    raise SystemExit(f"sitRepose: foreLegs bone {b!r} is not a skin joint")
            iu, il, if_ = (nm.index(b) for b in c)
            if g.parent.get(il) != iu or g.parent.get(if_) != il:
                raise SystemExit(f"sitRepose: foreleg {c} is not an upper -> lower -> hand chain")
            j = iu
            while j is not None and j != hi:
                j = g.parent.get(j)
            if j != hi:
                raise SystemExit(f"sitRepose: foreleg {c} is not under {hips}")
            fchains.append(c)
            bind.update({b: bw[b] for b in c})
        for c in legs:
            if c[2] not in bw:
                raise SystemExit(f"sitRepose: hind foot {c[2]!r} is not a skin joint (foreLegs measures from it)")
            bind[c[2]] = bw[c[2]]
    done = {}
    for clip, shape in op["clips"].items():
        try:
            a = g.anim(clip)
        except KeyError:
            raise SystemExit(f"sitRepose: no clip {clip!r}") from None
        if any(s.get("interpolation", "LINEAR") not in ("LINEAR", "STEP") for s in a["samplers"]):
            raise SystemExit(f"sitRepose: {clip} has non-LINEAR/STEP samplers")
        grid = np.array(sorted({round(float(x), 6) for s in a["samplers"] for x in g.read(s["input"])[:, 0]}))
        end = float(grid[-1]) if grid[-1] > 0 else 1.0
        w = sit_weight(shape, grid / end)
        loc = g.sample_local(clip, grid)
        mats = g.world(loc)
        ht, hr = loc[hi][0].copy(), loc[hi][1].copy()
        rot = {b: loc[nm.index(b)][1].copy() for b in [b for c in legs for b in c] + [t for t, _ in turns]}
        for c in legs:
            for kc in g.nodes[nm.index(c[2])].get("children", []):
                rot.setdefault(nm[kc], loc[kc][1].copy())
        for c in fchains:
            for b in c:
                rot.setdefault(b, loc[nm.index(b)][1].copy())
        moved = 0
        for k in range(len(grid)):
            if w[k] <= 1e-9:
                continue
            moved += 1
            Mh = mats[hi][k]
            piv = np.mean([mats[nm.index(c[0])][k][:3, 3] for c in legs], 0)
            R = np.eye(4)
            R[:3, :3] = axis_rot(op.get("pitch", 0.0) * w[k])
            R[:3, 3] = piv - R[:3, :3] @ piv
            D = np.eye(4)
            D[1, 3] = -op.get("drop", 0.0) * height * w[k]
            Mh2 = D @ R @ Mh
            ride = Mh2 @ np.linalg.inv(Mh)
            Lh = np.linalg.inv(mats[par][k]) @ Mh2
            ht[k] = Lh[:3, 3]
            hr[k] = G.mat_q(Lh[:3, :3] / np.linalg.norm(Lh[:3, :3], axis=0))
            for c in legs:
                iu, il, if_ = (nm.index(b) for b in c)
                Mu, Ml, Mf = mats[iu][k], mats[il][k], mats[if_][k]
                Mu1 = ride @ Mu
                H1 = Mu1[:3, 3]
                K1, A1 = two_bone(H1, Mu[:3, 3], Ml[:3, 3], Mf[:3, 3])
                Mu2 = Mu1.copy()
                Mu2[:3, :3] = rot_between((ride @ Ml)[:3, 3] - H1, K1 - H1) @ Mu1[:3, :3]
                Ml1 = Mu2 @ np.linalg.inv(Mu) @ Ml
                Ml2 = Ml1.copy()
                Ml2[:3, :3] = rot_between((Mu2 @ np.linalg.inv(Mu) @ Mf)[:3, 3] - Ml1[:3, 3],
                                          A1 - Ml1[:3, 3]) @ Ml1[:3, :3]
                Mf2 = Ml2 @ np.linalg.inv(Ml) @ Mf
                Mf2[:3, :3] = Mf[:3, :3]          # the foot keeps its world rotation
                rot[c[0]][k] = local_q(Mh2, Mu2)
                rot[c[1]][k] = local_q(Mu2, Ml2)
                rot[c[2]][k] = local_q(Ml2, Mf2)
                for kc in g.nodes[if_].get("children", []):   # toes keep their world rotation
                    rot[nm[kc]][k] = local_q(Mf2, mats[kc][k])
            neww = {hi: Mh2}
            for b, deg in turns:
                ib = nm.index(b)
                top = next(j for j in anc[b] if j in neww)
                Mn = neww[top] @ np.linalg.inv(mats[top][k]) @ mats[ib][k]
                Mn[:3, :3] = axis_rot(deg * w[k]) @ Mn[:3, :3]
                neww[ib] = Mn
                pb = g.parent[ib]
                Pn = neww[pb] if pb in neww else neww[top] @ np.linalg.inv(mats[top][k]) @ mats[pb][k]
                rot[b][k] = local_q(Pn, Mn)
            for c in fchains:
                iu, il, if_ = (nm.index(b) for b in c)
                Mu, Ml, Mf = mats[iu][k], mats[il][k], mats[if_][k]
                ju = g.parent[iu]
                top = ju
                while top not in neww:
                    top = g.parent[top]
                Pu = neww[top] @ np.linalg.inv(mats[top][k]) @ mats[ju][k]     # the upper's parent, re-posed
                Mu1 = Pu @ np.linalg.inv(mats[ju][k]) @ Mu
                H1 = Mu1[:3, 3]
                bu, bf = bind[c[0]], bind[c[2]]
                l1 = float(np.linalg.norm(Ml[:3, 3] - Mu[:3, 3]))
                l2 = float(np.linalg.norm(Mf[:3, 3] - Ml[:3, 3]))
                # the hand's floor is the hind feet's: the bind hand height over the bind hind feet, carried by the
                # clip's own hind-foot height at this key (a clip that starts lifted keeps its hands lifted with it)
                dy = float(np.mean([mats[nm.index(h[2])][k][1, 3] - bind[h[2]][1, 3] for h in legs]))
                T = np.array([H1[0] + bf[0, 3] - bu[0, 3], bf[1, 3] + dy, H1[2] + fore["reach"] * height])
                T = Mf[:3, 3] + w[k] * (T - Mf[:3, 3])
                K1, A1 = two_bone_to(H1, l1, l2, T, np.array([0.0, 0.0, -1.0]))
                Mu2 = Mu1.copy()
                Mu2[:3, :3] = rot_between((Mu1 @ np.linalg.inv(Mu) @ Ml)[:3, 3] - H1, K1 - H1) @ Mu1[:3, :3]
                Ml1 = Mu2 @ np.linalg.inv(Mu) @ Ml
                Ml2 = Ml1.copy()
                Ml2[:3, :3] = rot_between((Mu2 @ np.linalg.inv(Mu) @ Mf)[:3, 3] - Ml1[:3, 3],
                                          A1 - Ml1[:3, 3]) @ Ml1[:3, :3]
                Mf2 = Ml2 @ np.linalg.inv(Ml) @ Mf
                sc = np.linalg.norm(Mf[:3, :3], axis=0)
                Mf2[:3, :3] = blend_rot(unit_cols(Mf[:3, :3]), unit_cols(bf[:3, :3]), float(w[k])) * sc
                rot[c[0]][k] = local_q(Pu, Mu2)
                rot[c[1]][k] = local_q(Mu2, Ml2)
                rot[c[2]][k] = local_q(Ml2, Mf2)
        tgt = {(hi, "translation"): ht, (hi, "rotation"): hr}
        tgt.update({(nm.index(b), "rotation"): v for b, v in rot.items()})
        write_channels(g, a, grid, tgt, "LINEAR")
        done[clip] = {"shape": shape, "keys": len(grid), "keysMoved": moved}
    return {"op": "sitRepose", "pitch": op.get("pitch", 0.0), "drop": op.get("drop", 0.0),
            "heightUsed": round(height, 6), "turns": [[b, d] for b, d in turns], "foreLegs": fore, "clips": done}


def qmul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Hamilton product of xyzw quaternions, a (n,4) times b (4,)."""
    x1, y1, z1, w1 = a[:, 0], a[:, 1], a[:, 2], a[:, 3]
    x2, y2, z2, w2 = b
    return np.stack([w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
                     w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
                     w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
                     w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2], 1)


# ---------------------------------------------------------------------------------------------------- master sync
def master_frame_map(segments: list[dict], sources: list[str]) -> list[tuple[str, int] | None]:
    """Per master frame t: (Unit clip, key index) it shows in the shipped clips, or None. build_unit.py's rule: the clip
    Unit_<contractSuffix> is the longest segment of that suffix (the first one on a tie), its key i = master frame
    globalStart + i; any other segment's frame (idle bookends) maps to the shipped frame of the same DEF PNG."""
    chosen: dict = {}
    for sg in segments:
        n = "Unit_" + sg["contractSuffix"]
        if n not in chosen or sg["frameCount"] > chosen[n]["frameCount"]:
            chosen[n] = sg
    out: list = [None] * len(sources)
    by_png: dict = {}
    for n, sg in sorted(chosen.items(), key=lambda kv: kv[1]["globalStart"]):
        for i, t in enumerate(range(sg["globalStart"], sg["globalEnd"])):
            out[t] = (n, i)
            by_png.setdefault(sources[t], (n, i))
    for t, src in enumerate(sources):
        if out[t] is None:
            out[t] = by_png.get(src)
    return out


def master_mapping(unit: str) -> list | None:
    """The unit's master frame map from its linked master (None: no master_sequence.json, e.g. a non-mocap unit)."""
    msp = MOCAP_RUNS / unit / "linked_master/master_sequence/master_sequence.json"
    if not msp.is_file():
        return None
    ms = json.loads(msp.read_text(encoding="utf-8"))
    sources = [f["sourcePng"] for f in ms["frames"]]
    fjp = canonical_glb(unit).parent / f"{unit}_def_retarget.blend.frames.json"
    if fjp.is_file():
        fj = json.loads(fjp.read_text(encoding="utf-8"))
        if fj["segments"] != [[sg["clipKey"], sg["globalStart"], sg["globalEnd"]] for sg in ms["segments"]]:
            raise SystemExit(f"{unit}: masterSync: frames.json segments disagree with master_sequence.json")
        sources = fj["sources"]
    return master_frame_map(ms["segments"], sources)


def sync_master(g: Glb, g0: Glb, fmap: list | None) -> dict:
    """Rewrite the *_DEF_Master TRS channels on the master's own key grid: every mapped frame takes the patched Unit
    clip's pose at that clip's own key time (read from the input GLB's grid, before any regrid); unmapped frames keep
    their keys. Channels any mapped clip or the master drives are written (LINEAR, one key per master frame)."""
    names = [a["name"] for a in g.json.get("animations", []) if a.get("name", "").endswith(MASTER_SUFFIX)]
    if not names:
        return {"skipped": "no *_DEF_Master animation"}
    if len(names) != 1:
        raise SystemExit(f"masterSync: {len(names)} *_DEF_Master animations")
    if fmap is None:
        return {"master": names[0], "skipped": "no master_sequence.json for this unit"}
    ma = g.anim(names[0])
    mt = g0.key_grid(names[0])
    if len(mt) != len(fmap):
        raise SystemExit(f"masterSync: {names[0]} has {len(mt)} keys, the master sequence {len(fmap)} frames")
    have = {a["name"] for a in g.json["animations"]}
    slot = {"translation": 0, "rotation": 1, "scale": 2}
    loc_m = g.sample_local(names[0], mt)
    keys = {(c["target"]["node"], c["target"]["path"]) for c in ma["channels"] if c["target"]["path"] in slot}
    rows: dict = {}
    for t, m in enumerate(fmap):
        if m is not None and m[0] in have:
            rows.setdefault(m[0], []).append((t, m[1]))
    for clip in rows:
        keys |= {(c["target"]["node"], c["target"]["path"]) for c in g.anim(clip)["channels"] if c["target"]["path"] in slot}
    vals = {k: loc_m[k[0]][slot[k[1]]].copy() for k in keys}
    for clip, tr in rows.items():
        grid = g0.key_grid(clip)
        if max(i for _, i in tr) >= len(grid):
            raise SystemExit(f"masterSync: {clip} has {len(grid)} keys, the master maps frame {max(i for _, i in tr)}")
        loc = g.sample_local(clip, grid[[i for _, i in tr]])
        ts = [t for t, _ in tr]
        for k in keys:
            vals[k][ts] = loc[k[0]][slot[k[1]]]
    before = loc_m
    write_channels(g, ma, mt, vals, "LINEAR")
    moved = 0.0
    for (node, path), v in vals.items():
        if path == "rotation":
            d = np.abs(np.sum(v / np.linalg.norm(v, axis=1, keepdims=True) * before[node][1], 1))
            moved = max(moved, float(np.degrees(2 * np.arccos(np.clip(d, 0, 1))).max()))
    synced = sum(len(v) for v in rows.values())
    return {"master": names[0], "frames": len(fmap), "synced": synced,
            "unmapped": [t for t, m in enumerate(fmap) if m is None or m[0] not in have],
            "clips": {c: len(v) for c, v in sorted(rows.items())}, "maxRotationChangeDeg": round(moved, 2)}


def master_rows(g: Glb, fmap: list | None) -> tuple[str | None, list]:
    """(master name, [(master frame, Unit clip, key index)]) of the mapped master frames whose clip exists."""
    names = [a["name"] for a in g.json.get("animations", []) if a.get("name", "").endswith(MASTER_SUFFIX)]
    if len(names) != 1 or fmap is None:
        return None, []
    have = {a["name"] for a in g.json["animations"]}
    return names[0], [(t, m[0], m[1]) for t, m in enumerate(fmap) if m is not None and m[0] in have]


def verify_master_copy(g: Glb, g0: Glb, fmap: list | None, height: float) -> dict:
    """After sync_master: every mapped master frame must show the shipped Unit_* pose it copies -- per joint, world
    rotation within MASTER_COPY_TOL_DEG and world position within MASTER_COPY_TOL_POS x body height (the tear gate
    counts those poses once, on the Unit_* clips, so the master must be a faithful copy). Refuses otherwise."""
    name, rows = master_rows(g, fmap)
    if not rows:
        return {"checked": 0}
    mt = g0.key_grid(name)
    Wm = g.world(g.sample_local(name, mt[[t for t, _, _ in rows]]))
    worst_deg, worst_pos = 0.0, 0.0
    for clip in dict.fromkeys(c for _, c, _ in rows):
        idx = [(r, i) for r, (_, c, i) in enumerate(rows) if c == clip]
        grid = g0.key_grid(clip)
        Wc = g.world(g.sample_local(clip, grid[[i for _, i in idx]]))
        sel = [r for r, _ in idx]
        for j in Wm:
            A, B = Wm[j][sel], Wc[j]
            worst_pos = max(worst_pos, float(np.linalg.norm(A[:, :3, 3] - B[:, :3, 3], axis=1).max()) / height)
            Ra, Rb = A[:, :3, :3], B[:, :3, :3]
            Ra = Ra / np.linalg.norm(Ra, axis=1, keepdims=True); Rb = Rb / np.linalg.norm(Rb, axis=1, keepdims=True)
            tr = np.clip((np.einsum("nij,nij->n", Ra, Rb) - 1) / 2, -1, 1)
            worst_deg = max(worst_deg, float(np.degrees(np.arccos(tr)).max()))
    rec = {"checked": len(rows), "maxRotationDeg": round(worst_deg, 5), "maxPositionOverHeight": round(worst_pos, 7),
           "limits": {"deg": MASTER_COPY_TOL_DEG, "posOverHeight": MASTER_COPY_TOL_POS}}
    if worst_deg > MASTER_COPY_TOL_DEG or worst_pos > MASTER_COPY_TOL_POS:
        raise SystemExit(f"masterSync: {name} is not a faithful copy of the shipped Unit_* clips ({json.dumps(rec)}); "
                         "the tear gate counts each shipped pose once, so the master must match them")
    return rec


def master_duplicate_poses(g0: Glb, fmap: list | None) -> set:
    """{(master name, key time)} of the master frames that copy a shipped Unit_* pose: the tear gate skips their CS
    targets (each shipped pose is gated once, on its Unit_* clip; verify_master_copy proves the copy). Unmapped master
    frames stay in the gate."""
    name, rows = master_rows(g0, fmap)
    if not rows:
        return set()
    mt = g0.key_grid(name)
    return {(name, round(float(mt[t]), 4)) for t, _, _ in rows}


# ---------------------------------------------------------------------------------------------------- CS re-bake
def target_poses(g: Glb, body: Body, unit: str | None = None) -> list[tuple[int, str, float]]:
    """(target index, clip, key time) of every morph target: the weights key where the target is on (bake_cs keys it
    1 on its own frame, 0 either side). A target not found on exactly one key of its own clip refuses.
    A target of a clip the unit config's skipDefGroups leaves out of the export (bake_cs still bakes its shape keys) is
    an orphan, as in cs_rekey_glb.orphan_targets: it is not re-baked, and it must be weight 0 in every shipped clip.
    A target naming any other missing clip still refuses (2026-10-11 h3_medusa_warrior, h3_vampire_prince:
    CS_Unit_ShootFront targets, shoot groups skipped; user-approved 2026-10-11)."""
    clips = {a["name"]: a for a in g.json.get("animations", [])}
    skipped = skip_def_groups.skipped_clips(unit) if unit else {}
    out = []
    per_clip: dict = {}
    orphan_ti = []
    for ti, name in enumerate(body.target_names):
        if not name.startswith("CS_"):
            raise SystemExit(f"morph target {name!r} is not a bake_cs target; the lane re-bakes CS targets only")
        clip = name[3:].rsplit("_", 1)[0]
        if clip not in clips:
            if clip not in skipped:
                raise SystemExit(f"morph target {name} names no clip of the GLB")
            orphan_ti.append(ti)
            continue
        per_clip.setdefault(clip, []).append(ti)
    for cn, a in clips.items() if orphan_ti else ():
        for c in a["channels"]:
            if c["target"]["path"] == "weights" and c["target"]["node"] == body.node:
                s_ = a["samplers"][c["sampler"]]
                w_ = g.read(s_["output"]).reshape(len(g.read(s_["input"])), -1)
                if np.abs(w_[:, orphan_ti]).max() > 1e-6:
                    raise SystemExit(f"{cn} plays a CS_ target of a skipped clip ({sorted(skipped)})")
    for clip, tis in per_clip.items():
        a = clips[clip]
        ch = [c for c in a["channels"] if c["target"]["path"] == "weights" and c["target"]["node"] == body.node]
        if len(ch) != 1:
            raise SystemExit(f"{clip}: {len(ch)} morph weight channels on the body")
        s = a["samplers"][ch[0]["sampler"]]
        t = g.read(s["input"])[:, 0]
        w = g.read(s["output"]).reshape(len(t), -1)
        for ti in tis:
            on = np.flatnonzero(w[:, ti] >= 0.999)
            if len(on) > 1:
                # a one-frame clip (e.g. a 1-frame MoveStart) holds its frame on every key; same pose -> one target pose
                mats = g.world(g.sample_local(clip, t[on]))
                if all(np.abs(np.asarray(m)[1:] - np.asarray(m)[:1]).max() < 1e-6 for m in (mats.values() if isinstance(mats, dict) else mats)):
                    on = on[:1]
            if len(on) != 1:
                raise SystemExit(f"target {body.target_names[ti]} is on at {len(on)} keys of {clip} (expected one)")
            out.append((ti, clip, float(t[on[0]])))
    return out


def skin_matrices(g: Glb, body: Body, clip: str, time: float) -> np.ndarray:
    """Per skin joint 4x4 skin matrix at one time (batched per clip, cached on the Glb)."""
    cache = g.__dict__.setdefault("_skin_cache", {})
    if (clip, time) not in cache:
        times = sorted({t for c, t in body.__dict__.get("_pose_times", [(clip, time)]) if c == clip} | {time})
        mats = g.world(g.sample_local(clip, np.array(times)))
        M = np.stack([mats[j] for j in body.joints], 1) @ body.ibm[None]
        for k, t in enumerate(times):
            cache[(clip, t)] = M[k]
    return cache[(clip, time)]


def cs_rebake(g_old: Glb, g_new: Glb, body: Body, J0, W0, J1, W1, parity_only=False, clips=None,
              dup_poses: set | None = None, relax_ops: list | None = None, unit: str | None = None,
              clear_clips: set | None = None, body1: Body | None = None) -> tuple[dict, list]:
    """Per target: numpy CS offsets under the old and the new skin/pose; parity of the old against the stored target.
    relax_ops: stretchRelax ops, run on the re-baked targets of their clips before the tear gate measures them.
    body1: the patched GLB's body when an addJoints / cutFaces op changed the rig or the triangles (default: body).
    The old side (parity, the stretch gate's input) is then measured on `body` (the export's joints and triangles),
    the new side (the re-baked offsets, stretchRelax, the gate's output) on body1: the welded proxy of the written
    mesh, the one cs_rekey rebuilds downstream."""
    body1 = body if body1 is None else body1
    Wn0 = W0 / np.maximum(W0.sum(1, keepdims=True), 1e-9)
    Wn1 = W1 / np.maximum(W1.sum(1, keepdims=True), 1e-9)
    weld = CS.Weld(body.V, J0, Wn0, body.F)
    if not parity_only:
        # the new weights must keep the weld: members of one group (UV-seam copies) must still skin identically
        grp = {}
        for v in range(len(J1)):
            key = tuple(sorted((int(j), round(float(x), 3)) for j, x in zip(J1[v], Wn1[v]) if round(float(x), 3)))
            prev = grp.setdefault(int(weld.gid[v]), key)
            if prev != key:
                raise SystemExit(f"the patch splits weld group {weld.gid[v]} (vertex {v}): its UV-seam copies would skin "
                                 "differently and open a crack; widen the region ramps")
    # smooth with the bake's own iterations / factor (bake record), never the module defaults
    cache = weld.rest_deltas(body.V[weld.rep], *CS.bake_smoothing(
        (g_old.json.get("asset", {}).get("extras") or {}).get(CS.BAKE_STAMP)))
    excl = ((g_old.json.get("asset", {}).get("extras") or {}).get(CS.BAKE_STAMP) or {}).get("excludeBones") or []
    # a float64 bake (cs_numpy.BAKE_STAMP v2) is numpy's own output: parity holds on every vertex, so no group is
    # split off as ill-conditioned (cond_edge 0); a legacy float32 bake keeps the COND_EDGE split (parity only)
    v2 = (g_old.json.get("asset", {}).get("extras") or {}).get(CS.BAKE_STAMP, {}).get("schema") == CS.BAKE_SCHEMA
    ce = 0.0 if v2 else CS.COND_EDGE * body.H
    poses = [p for p in target_poses(g_old, body, unit) if clips is None or p[1] in clips]
    body._pose_times = body1._pose_times = [(c, t) for _, c, t in poses]
    errs, stored_mag, changed_v, changed_t, support_errs = [], [], 0, 0, []
    worst = {"conditioned": 0.0, "illConditioned": 0.0}
    ill_total, ill_changed, all_total, all_changed = 0, 0, 0, 0
    stretch = {k: {"edgesOver2x": 0, "worst": 0.0} for k in ("input", "output")}
    stretch["dedupedMasterTargets"] = 0
    new_targets = []
    # the bake's correctiveSmooth.excludeBones (bake record), applied with each skin's own weights
    weld.set_exclusion(CS.exclusion_share(J0, Wn0, body.jnames, excl)[weld.rep] if excl else None)
    R0 = CS.offsets_batch(weld, body.V, J0, Wn0, [skin_matrices(g_old, body, c, t) for _, c, t in poses], cache, ce)
    # the new skin's own welded proxy: a weight edit that merges or splits weld groups (UV-seam copies or coincident
    # vertices whose weight rows now match / differ) changes bake_cs's proxy, and cs_rekey downstream rebuilds it from
    # the written weights; offsets under the new skin must come from that same proxy or its parity check refuses
    weld1, cache1 = weld, cache
    if not parity_only:
        w1 = CS.Weld(body1.V, J1, Wn1, body1.F)
        if body1 is not body or w1.ng != weld.ng or not np.array_equal(w1.gid, weld.gid):
            weld1 = w1
            cache1 = weld1.rest_deltas(body1.V[weld1.rep], *CS.bake_smoothing(
                (g_old.json.get("asset", {}).get("extras") or {}).get(CS.BAKE_STAMP)))
    # the new side's exclusion is the patched record's: addJoints appends its joints to the bake's excludeBones
    excl1 = ((g_new.json.get("asset", {}).get("extras") or {}).get(CS.BAKE_STAMP) or {}).get("excludeBones") or []
    weld1.set_exclusion(CS.exclusion_share(J1, Wn1, body1.jnames, excl1)[weld1.rep] if excl1 else None)
    R1 = None if parity_only else         CS.offsets_batch(weld1, body1.V, J1, Wn1, [skin_matrices(g_new, body1, c, t) for _, c, t in poses], cache1, ce)
    for pi, (ti, clip, tm) in enumerate(poses):
        stored = g_old.read(body.targets[ti])
        d0, c0 = R0[pi]
        e = np.linalg.norm(d0 - stored, axis=1)
        errs.append(e[c0])
        ill_total += int((~c0).sum())
        all_total += len(c0)
        stored_mag.append(float(np.linalg.norm(stored, axis=1).max()))
        if parity_only:
            continue
        d1, c1 = R1[pi]
        dd = d1 - d0
        n = np.linalg.norm(dd, axis=1)
        m = n > KEEP_EPS
        cond = c0 & c1
        out = stored.copy()
        # conditioned: Blender's bytes plus the numpy difference (parity-proven); ill-conditioned: numpy's own offset,
        # since Blender's value there is float32 noise (bake_cs's own noise measured worse than numpy: h3_jotunn_upg_alt
        # edges>2x over all targets 2138 stored vs 878 numpy, 979 with no CS at all; worst stretch equal)
        out[m & cond] = stored[m & cond] + dd[m & cond]
        out[m & ~cond] = d1[m & ~cond]
        if m.any():
            changed_t += 1
            changed_v = max(changed_v, int(m.sum()))
            all_changed += int(m.sum())
            ill_changed += int((m & ~cond).sum())
            if (m & cond).any():
                worst["conditioned"] = max(worst["conditioned"], float(n[m & cond].max()))
                support_errs.append(e[m & cond])
            if (m & ~cond).any():
                worst["illConditioned"] = max(worst["illConditioned"], float(n[m & ~cond].max()))
        if clear_clips and clip in clear_clips:   # setTracks clearCorrectives: the authored clip ships on the plain skin
            out = np.zeros_like(stored)
        new_targets.append((ti, out))
    relaxed = [] if parity_only else op_stretch_relax(relax_ops or [], weld1, body1, J1, Wn1, g_new, poses, new_targets)
    for pi, (ti, clip, tm) in enumerate(poses):
        if parity_only:
            break
        stored, out = g_old.read(body.targets[ti]), new_targets[pi][1]
        if dup_poses and (clip, round(tm, 4)) in dup_poses:   # a master copy of a shipped pose: gated on its Unit_* clip
            stretch["dedupedMasterTargets"] += 1
            continue
        for k, (J_, W_, g_, D_, b_) in (("input", (J0, Wn0, g_old, stored, body)), ("output", (J1, Wn1, g_new, out, body1))):
            r = edge_stretch(b_, J_, W_, skin_matrices(g_, b_, clip, tm), D_)
            stretch[k]["edgesOver2x"] += int((r > STRETCH_RATIO).sum())
            stretch[k]["worst"] = max(stretch[k]["worst"], round(float(r.max()), 3))

    def stats(parts):
        E = np.concatenate(parts) if parts and sum(len(x) for x in parts) else np.zeros(1)
        return {"p99OverHeight": round(float(np.percentile(E, 99)) / body.H, 6),
                "maxOverHeight": round(float(E.max()) / body.H, 6),
                "meanOverHeight": round(float(E.mean()) / body.H, 7), "samples": int(sum(len(x) for x in parts))}
    rec = {"targets": len(poses), "weldGroups": weld.ng, "edges": int(len(weld.edges)),
           "sourceBake": CS.BAKE_SCHEMA if v2 else "legacy float32 (Blender CORRECTIVE_SMOOTH)",
           "storedMaxOverHeight": round(max(stored_mag or [0]) / body.H, 4),
           "limits": {"p99": PARITY_P99_MAX, "max": PARITY_MAX_MAX, "condEdgeOverHeight": CS.COND_EDGE},
           # the gate: conditioned vertices where the lane replaces stored bits (every other vertex keeps Blender's
           # own bytes); ill-conditioned vertices (a collapsed smoothed neighbourhood, Blender's float32 noise) are
           # counted, not gated -- the delivery gates after this stage measure the result
           "parity": stats(errs if parity_only else support_errs),
           "parityWholeMeshConditioned": stats(errs),
           "illConditionedShare": round(ill_total / max(all_total, 1), 4)}
    if not parity_only:
        rec.update({"targetsChanged": changed_t, "maxVerticesChangedPerTarget": changed_v,
                    "changedIllConditionedShare": round(ill_changed / max(all_changed, 1), 4),
                    "maxOffsetChangeOverHeight": {k: round(v / body.H, 5) for k, v in worst.items()},
                    "stretch": stretch})
        if relaxed:
            rec["stretchRelax"] = relaxed
    return rec, new_targets


def op_stretch_relax(ops: list, weld, body: Body, J, Wn, g: Glb, poses: list, new_targets: list) -> list:
    """stretchRelax: the strain-limiting corrective (stretch_relax.py) on the re-baked CS targets of each op's clips,
    written into new_targets in place; refuses an unknown clip, a clip with no CS target and a slide past maxMove."""
    import stretch_relax as SR
    recs = []
    clips_all = {a["name"] for a in g.json.get("animations", [])}
    for op in ops:
        missing = [c for c in op["clips"] if c not in clips_all]
        if missing:
            raise SystemExit(f"stretchRelax: clips {missing} are not in the GLB")
        sel = [pi for pi, (_, c, _) in enumerate(poses) if c in op["clips"]]
        if not sel:
            raise SystemExit(f"stretchRelax: clips {op['clips']} carry no CS_ target")
        if "bones" in op:
            ids = sorted({i for i, n in enumerate(body.jnames) for pat in op["bones"] if fnmatch.fnmatchcase(n, pat)})
            if not ids:
                raise SystemExit(f"stretchRelax: bones {op['bones']} match no joint of the skin")
            movable = (np.isin(J, ids) * Wn).sum(1) > 0.01
        else:
            movable = np.ones(len(J), bool)
        Sks = [skin_matrices(g, body, poses[pi][1], poses[pi][2]) for pi in sel]
        before = [int((edge_stretch(body, J, Wn, Sk, new_targets[pi][1]) > STRETCH_RATIO).sum())
                  for Sk, pi in zip(Sks, sel)]
        outs, moved, pinned = SR.relax_batch(weld, body.V, J, Wn, Sks, [new_targets[pi][1] for pi in sel], movable,
                                     op["ratio"], op["iterations"], op["smooth"])
        limit = float(op.get("maxMove", RELAX_MAX_MOVE))
        per = []
        for k, pi in enumerate(sel):
            ti, clip, tm = poses[pi]
            if moved[k] > limit * body.H:
                raise SystemExit(f"stretchRelax: {clip} t={tm:.4f} slides a weld group {moved[k] / body.H:.4f} x the "
                                 f"body height, past maxMove {limit}; this is a reshape, not a strain limit")
            rest = float(np.linalg.norm(outs[k] - new_targets[pi][1], axis=1).max())
            if rest > limit * body.H / SR.SIGMA_MIN + 1e-9:
                raise SystemExit(f"stretchRelax: {clip} t={tm:.4f} changes a rest offset by {rest / body.H:.4f} x the "
                                 f"body height, past maxMove / SIGMA_MIN ({limit / SR.SIGMA_MIN}); refusing")
            new_targets[pi] = (ti, outs[k].astype(np.float32).astype(np.float64))
            after = int((edge_stretch(body, J, Wn, Sks[k], new_targets[pi][1]) > STRETCH_RATIO).sum())
            per.append({"clip": clip, "time": round(tm, 4), "edgesOver2x": [before[k], after],
                        "maxMoveOverHeight": round(float(moved[k]) / body.H, 5),
                        "maxRestChangeOverHeight": round(rest / body.H, 5), "pinnedGroups": int(pinned[k])})
        recs.append({"op": "stretchRelax", "clips": op["clips"], "ratio": op["ratio"], "iterations": op["iterations"],
                     "smooth": op["smooth"], "bones": op.get("bones"), "maxMove": limit,
                     "movableVertices": int(movable.sum()), "poses": per,
                     "edgesOver2x": [sum(before), sum(p["edgesOver2x"][1] for p in per)],
                     "note": op.get("note", "")})
    return recs


def edge_stretch(body: Body, J, Wn, Sk, D) -> np.ndarray:
    """Per rest edge (longer than 1e-6), posed length / rest length of the body skinned with (J, Wn) after offsets D."""
    if not hasattr(body, "_edges"):
        E = np.unique(np.sort(np.concatenate([body.F[:, [0, 1]], body.F[:, [1, 2]], body.F[:, [2, 0]]]), 1), axis=0)
        L = np.linalg.norm(body.V[E[:, 0]] - body.V[E[:, 1]], axis=1)
        body._edges, body._rest_len = E[L > 1e-6], L[L > 1e-6]
    if CS.resolve_device() == "cuda":
        import cs_torch
        return cs_torch.edge_stretch(body, J, Wn, Sk, D)
    X = np.c_[body.V + D, np.ones(len(body.V))]
    Y = np.zeros((len(X), 3))
    for k in range(J.shape[1]):
        Y += Wn[:, k:k + 1] * np.einsum("nij,nj->ni", Sk[J[:, k]], X)[:, :3]
    E = body._edges
    return np.linalg.norm(Y[E[:, 0]] - Y[E[:, 1]], axis=1) / body._rest_len


def parity_errors(rec: dict) -> list[str]:
    p = rec["parity"]
    bad = []
    st = rec.get("stretch")
    if st:
        if st["output"]["edgesOver2x"] > st["input"]["edgesOver2x"]:
            bad.append(f"the patched body tears more edges past {STRETCH_RATIO}x over all targets "
                       f"({st['input']['edgesOver2x']} -> {st['output']['edgesOver2x']})")
        if st["output"]["worst"] > st["input"]["worst"] * WORST_STRETCH_SLACK:
            bad.append(f"the patched body's worst edge stretch rose {st['input']['worst']} -> {st['output']['worst']}")
    if p["p99OverHeight"] > PARITY_P99_MAX:
        bad.append(f"numpy CS parity p99 {p['p99OverHeight']} of the body height > {PARITY_P99_MAX}")
    if p["maxOverHeight"] > PARITY_MAX_MAX:
        bad.append(f"numpy CS parity max {p['maxOverHeight']} of the body height > {PARITY_MAX_MAX}")
    return bad


# ---------------------------------------------------------------------------------------------------- commands
def geometry_and_images(data: bytes) -> dict:
    sys.path.insert(0, str(ROOT / "tools/homm3_unit_look"))
    import glbpatch as LG  # noqa: E402
    lg = LG.Glb(data)
    imgs = [sha(lg.image_bytes(i)) for i in range(len(lg.json.get("images", [])))]
    body = lg.json["meshes"][lg.body_mesh_index()]["primitives"][0]
    normals = sha(lg.accessor_bytes(body["attributes"]["NORMAL"])) if "NORMAL" in body["attributes"] else None
    return {"geometrySha256": lg.geometry_sha256(), "normalSha256": normals, "imageSha256": imgs}


def patch_bytes(unit: str, data: bytes, spec: dict) -> tuple[bytes, dict]:
    bad = spec_errors(spec)
    if bad:
        raise SystemExit(f"{unit}: {CONFIG_KEY}: {'; '.join(bad)}")
    g0 = Glb(data)
    if STAMP in g0.json.get("asset", {}).get("extras", {}):
        raise SystemExit(f"{unit}: the GLB is already patched ({STAMP}); patch the verified export")
    g = Glb(data)
    body0 = Body(g0)                      # the export's rig and triangles: the CS parity / tear gate's input side
    body = Body(g)                        # rebuilt after an addJoints / cutFaces (the patched rig and triangles)
    J, W = body.J.copy(), body.W.copy()
    ops, topo = [], {}
    relax_ops = [op for op in spec["ops"] if op["op"] == "stretchRelax"]
    for op in spec["ops"]:
        if op["op"] == "stretchRelax":
            continue                      # runs on the re-baked CS targets, inside cs_rebake (recorded there)
        if op["op"] == "addJoints":
            r = op_add_joints(g, body, op)
            body = Body(g)
            topo.setdefault("jointsAdded", []).extend(n for n, _ in r["joints"])
        elif op["op"] == "cutFaces":
            r = op_cut_faces(g, body, op)
            body = Body(g)
            topo["facesCut"] = r["facesCut"]
            topo["cutTableSha256"] = op["sha256"]
        elif op["op"] == "moveWeights":
            J, W, r = op_move_weights(body, op, J, W)
        elif op["op"] == "diffuseWeights":
            J, W, r = op_diffuse_weights(body, op, J, W)
        elif op["op"] == "setWeights":
            J, W, r = op_set_weights(body, op, J, W)
        elif op["op"] == "sitRepose":
            r = op_sit_repose(g, op, body.H, body)
        elif op["op"] == "keyRotations":
            r = op_key_rotations(g, op)
        elif op["op"] == "keyTranslations":
            r = op_key_translations(g, op, body.H)
        elif op["op"] == "keyScales":
            r = op_key_scales(g, op)
        elif op["op"] == "setTracks":
            r = op_set_tracks(g, op)
        else:
            r = op_rotate_track(g, op)
        ops.append(r)
    fmap = master_mapping(unit)
    msync = sync_master(g, g0, fmap)
    if "synced" in msync:
        msync["copyCheck"] = verify_master_copy(g, g0, fmap, body.H)
    cs = None
    _bs = (g0.json.get("asset", {}).get("extras") or {}).get(CS.BAKE_STAMP, {}).get("schema")
    if body.targets and _bs != CS.BAKE_SCHEMA:
        kind = (f"a superseded float64 bake ({_bs})" if _bs in CS.SUPERSEDED_SCHEMAS
                else f"a legacy float32 bake (no {CS.BAKE_STAMP})")
        raise SystemExit(f"{unit}: the base's Corrective Smooth morphs are {kind}, not {CS.BAKE_SCHEMA}; run the unit's "
                         f"full chain once (fleet_rebuild.py {unit}) so bake_cs.py re-bakes it with the current rule and "
                         "retains a fresh base (docs/homm3_cs_bake_float64.md)")
    if relax_ops and not body.targets:
        raise SystemExit(f"{unit}: stretchRelax corrects CS_ targets and the body has none")
    if body.targets:
        cs, new_targets = cs_rebake(g0, g, body0, body0.J, body0.W, J, W, body1=body,
                                     dup_poses=master_duplicate_poses(g0, fmap) if "copyCheck" in msync else None,
                                     relax_ops=relax_ops, unit=unit,
                                     clear_clips={c for op in spec["ops"] if op["op"] == "setTracks"
                                                  and op.get("clearCorrectives") for c in tracks_table(op)[0]["clips"]})
        ops += cs.get("stretchRelax", [])
        perr = parity_errors(cs)
        if perr:
            raise SystemExit(f"{unit}: refusing the numpy CS re-bake: {'; '.join(perr)} ({json.dumps(cs['parity'])}, "
                             f"stretch {json.dumps(cs.get('stretch'))}); fix the patch or use the full chain")
    refs = accessor_refs(g)
    at = body.prim["attributes"]
    if J.max() > {5121: 255, 5123: 65535}[g.json["accessors"][at["JOINTS_0"]]["componentType"]]:
        raise SystemExit(f"{unit}: a joint index past the JOINTS_0 component range")
    overwrite(g, at["JOINTS_0"], J, refs)
    overwrite(g, at["WEIGHTS_0"], W, refs)
    for ti, arr in (new_targets if body.targets else []):
        overwrite(g, body.targets[ti], arr, refs)
    before = geometry_and_images(data)
    if topo:
        topo["sourceGeometrySha256"] = before["geometrySha256"]
    g.json.setdefault("asset", {}).setdefault("extras", {})[STAMP] = {
        "schema": SCHEMA, "tool": "tools/homm3_glb_patch/patch_glb.py", "sourceGlbSha256": sha(data),
        "configSha256": canonical_sha(spec), "reason": spec["reason"], "ops": ops, "masterSync": msync, "csRebake": cs,
        **({"topology": topo} if topo else {}),
        "proof": "generated artifact: numpy skin/track patch + differential CS re-bake; not built into a bundle, not in game"}
    out = g.to_bytes()
    after = geometry_and_images(out)
    if topo.get("facesCut"):
        # the one declared geometry change: the index buffer lost exactly the table's faces. Everything else must be
        # the export's: images, normals, and (declared_cut_errors) the vertex data and the kept triangles in order
        topo["geometrySha256"] = after["geometrySha256"]
        out = g.to_bytes()                # the stamp now names the cut geometry
        same = {k: before[k] == after[k] for k in ("normalSha256", "imageSha256")}
        bad = declared_cut_errors(out, data)
        if not all(same.values()) or bad or after["geometrySha256"] == before["geometrySha256"]:
            raise SystemExit(f"{unit}: cutFaces changed more than the declared faces ({same}, {bad}); refusing")
    elif before != after:
        raise SystemExit(f"{unit}: the patch changed geometry, normals or images ({before} -> {after}); refusing")
    return out, {"ops": ops, "masterSync": msync, "csRebake": cs, **({"topology": topo} if topo else {}), **after}


def apply_bytes(unit: str, data: bytes, path: Path, out: Path | None = None):
    """The patch stage on GLB bytes, in memory: a stage_sidecar.StageResult (the patched bytes and the patch.json
    sidecar naming `path` as source and `out` as output, as the in-place CLI writes it), or None (no "glbPatch")."""
    spec = unit_config(unit).get(CONFIG_KEY)
    if spec is None:
        return None
    out = Path(out or path)
    t0 = time.perf_counter()
    res, rec = patch_bytes(unit, data, spec)
    side = {"schema": SCHEMA, "unit": unit, "sourceGlb": str(path), "sourceGlbSha256": sha(data),
            "outputGlb": str(out), "outputGlbSha256": sha(res), "configSha256": canonical_sha(spec),
            "seconds": round(time.perf_counter() - t0, 2), **rec}
    return stage_sidecar.result(res, data, "patch", side, {
        "unit": unit, "out": str(out), "outputGlbSha256": sha(res)[:12], "ops": rec["ops"],
        "csRebake": rec["csRebake"], "seconds": side["seconds"]})


def cmd_apply(args) -> int:
    if unit_config(args.unit).get(CONFIG_KEY) is None:
        print(json.dumps({"unit": args.unit, "skipped": f"no {CONFIG_KEY} in the unit config"}))
        return 3
    p = Path(args.glb or canonical_glb(args.unit))
    out = Path(args.out or p)
    r = apply_bytes(args.unit, p.read_bytes(), p, out)
    stage_sidecar.commit(out, r)
    print(json.dumps(r.report))
    return 0


def cmd_parity(args) -> int:
    p = Path(args.glb or canonical_glb(args.unit))
    g = Glb.load(p)
    body = Body(g)
    if not body.targets:
        print(json.dumps({"unit": args.unit, "targets": 0}))
        return 0
    rec, _ = cs_rebake(g, g, body, body.J, body.W, body.J, body.W, parity_only=True,
                       clips=set(args.clips.split(",")) if args.clips else None, unit=args.unit)
    bad = parity_errors(rec)
    print(json.dumps({"unit": args.unit, "glb": str(p), **rec, "ok": not bad, "errors": bad}))
    return 1 if bad else 0


def stamp_errors(js: dict) -> list[str]:
    st = js.get("asset", {}).get("extras", {}).get(STAMP)
    if not isinstance(st, dict):
        return [f"no {STAMP} stamp"]
    bad = []
    if st.get("schema") != SCHEMA:
        bad.append(f"{STAMP} schema {st.get('schema')!r} != {SCHEMA}")
    for k in ("sourceGlbSha256", "configSha256"):
        if not (isinstance(st.get(k), str) and len(st[k]) == 64):
            bad.append(f"{STAMP} has no {k}")
    if not isinstance(st.get("ops"), list) or not st["ops"]:
        bad.append(f"{STAMP} records no ops")
    cs = st.get("csRebake")
    if cs is not None and parity_errors(cs):
        bad.append(f"{STAMP} csRebake parity out of bounds: {parity_errors(cs)}")
    return bad


def cmd_check(args) -> int:
    n = 0
    for p in args.glbs:
        e = stamp_errors(Glb.load(Path(p)).json)
        print(json.dumps({"glb": p, "ok": not e, "errors": e}))
        n += bool(e)
    return 1 if n else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("apply")
    s.add_argument("unit")
    s.add_argument("--glb", type=Path)
    s.add_argument("--out", type=Path)
    s = sub.add_parser("parity")
    s.add_argument("unit")
    s.add_argument("--glb", type=Path)
    s.add_argument("--clips", help="comma list: measure only these clips' targets (e.g. clips a later stage left alone)")
    s = sub.add_parser("check")
    s.add_argument("glbs", nargs="+")
    for s in (sub.choices["apply"], sub.choices["parity"]):
        s.add_argument("--device", choices=CS.DEVICES,
                       help="CS re-bake device (default: HOMM3_CS_DEVICE, else cuda; cpu = the numpy reference)")
    a = ap.parse_args(argv)
    if getattr(a, "device", None):
        os.environ["HOMM3_CS_DEVICE"] = a.device
    return {"apply": cmd_apply, "parity": cmd_parity, "check": cmd_check}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
