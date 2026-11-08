# HoMM3 DEF → mesh retarget (Blender, headless)

Animates each Tower unit's Meshy mesh from its original HoMM3 battle DEF and exports a
GLB with one animation per DEF clip. All 21 Tower units are built; per-unit numbers are in
`artifacts/homm3_def_retarget/SUMMARY.md`.

Proof state: **generated artifact validated.** Every GLB round-trips against its .blend
(`verify_glb.py`: all clips match to <1e-4, loop clips close exactly). Nothing here is
imported into Unity, installed, or runtime-proven.

## Method

1. **Owned skeleton.** Meshy's UniRig *weights* are discarded (on the Gremlin a finger
   bone owned 1517 vertices of robe). `auto_joints.py` seeds 27 Mixamo-named joints from
   UniRig's *layout* (spine = centre-line chain that climbs highest; arms = widest spine
   branches; legs = chains ending in a foot near the ground; a missing side is mirrored).
   Seeds are checked with a skeleton overlay and hand-placed where they fail (gargoyles:
   wings taken for arms; genie vizier: arms up its blades; nagas: extra arm pairs).
2. **Weights** (`surface_weights.py`, needs scipy): bone heat on a welded copy, then
   - hanging sleeves cut free of the robe and owned by the arm chain (Meshy fuses them;
     any blend across the fusion tears when an arm lifts);
   - robe above the boots keeps `skirtLegShare` of the leg motion, the rest goes to Hips.
3. **Rigid regions** (`props`, `wings`, `flail` in the unit config) are cut free along
   their boundary and bound 100% to one bone: staffs, bolts, blades, the flail and wings.
   A prop can be colour-gated (`minBlueOverRed`) where it crosses the body (giant bolts).
4. **Motion** from the DEF capture (`raw_capture.npz`, one pose per DEF frame), using
   joint directions only (`pred_rot6d` disagrees with `pred_position`; capture bone lengths
   vary up to 40%). Torso/head take a full frame from the hip and shoulder lines. Limbs
   either add the capture's change since idle frame 0 to the mesh's rest direction, or,
   for bones listed in `absoluteLimbs`, point along the capture's own direction; absolute
   is used only where the rest limb is within `absoluteMaxRestAngle` (35°) of the capture's
   idle limb, because crossed or mis-seeded arms would otherwise deform the rest pose.
   Absolute arms put a mage's raised staff where the DEF has it; the change-based method
   swung it flat.
5. **Non-humanoid bodies** (the capture is a human skeleton):
   - `tail` (nagas): 12 bones along the snake body's centreline, found by distance *along the
     surface* from the waist; each vertex takes its position along the body by projection onto
     that centreline. Only the tube around the centreline is tail (blades resting on the coil
     are not); low parts the mask missed are grown in by proximity; triangles straddling tail and
     a blade are split off to the blade; the waist blends into the torso. Each frame the tail
     rides with the hips near the waist, stays planted where it lies, and in Move (half in
     MoveStart/MoveEnd) uncoils into a wave trailing behind, one wave cycle per Move clip so the
     loop closes. `metalBlades` binds long light unsaturated parts rigidly to the nearest hand.
   - `grounding: false` for floating/coiled units (genies, nagas).
   - `wings`: rigid wing bones swung by the DEF sprite's width relative to idle frame 0.
   - `silhouetteRefine`: per frame, a screen offset, a lean about the camera axis, extra wing
     spread (up to 170°, so wings can sweep up into the DEF's V) and, for `propAim` bones, a
     swing and tilt of the held prop about the hand, all searched to maximise silhouette IoU
     against the DEF frame. The prop swing is scanned coarsely first because a thin staff
     changes IoU only a little; it adds the wrist twist the capture lacks.
   - `armCut` (genies): forearms/hands fused to the chest are cut free where they are the
     nearest bone.
   - `borrowClips` (Colossus): its DEF idle is one frame, so `Unit_Idle` uses the Titan's
     8-frame idle retargeted onto the Colossus mesh.
   - Deaths: `shatter` (golem, gargoyles) cuts a hidden duplicate of the mesh into chunks that
     take the body's pose at the break frame and fall with gravity, spin and bounce while the
     body collapses; the rubble mesh is exported in the same GLB and keyed near-zero scale
     outside Death. `shrinkOut` (genies) shrinks the body to a point on the ground where the
     DEF genie returns to its lamp.
6. **Props from the sprite.** The gremlin flail ball is tracked in every DEF frame (palette
   colours learned from a seed pixel) and placed on its view ray at chain length.
7. **Clips and loops.** One action per DEF clip (`Unit_<contractSuffix>`), one key per DEF
   frame at 12 fps, plus `<unit>_DEF_Master` (the whole reel). Idle and Move end with a
   closing key equal to their first pose; where the capture's last-to-first jump is larger
   than the clip's normal frame step, up to three transition keys ease the seam first.
8. **Sprite camera.** Front-left orthographic view (the model faces screen-right like the
   DEF), fitted to idle frame 0's opaque bbox; renders at DEF size so silhouettes overlay 1:1.

## Corrective-smooth morph targets (cloth tearing)

At 768 px review (`review_unit.sh`) skinned Meshy cloth shreds in large capture poses (fused
inner/outer layers, sleeves, hems). Weight smoothing (surface or 3D), leg damping and cut
changes did not fix it. `bake_cs.py`, run automatically at the end of every build, evaluates
Corrective Smooth (30 iterations, factor 0.7, rest = original coordinates; computed in float64 by
`tools/homm3_glb_patch/cs_numpy.py` with its degenerate-corner rule and harmonic fill, not Blender's float32 modifier,
see `docs/homm3_cs_bake_float64.md`; gate `tools/validate_homm3_cs_bake_contract.py`) for every
key of every action, converts the smoothed-minus-skinned offset back to rest space through each
vertex's blended bone rotation (exact for linear skinning) and stores it as one shape key per key
frame, animated 0→1→0 around its own frame in a KEY slot of that clip's action. `export_glb.py`
lays the clips out as same-named NLA tracks on the rig and the shape keys, so each glTF animation
carries its own morph-weight channel. h3_gremlin: reel edges >2x 6255 → 870; GLB 55 → 70 MB.
`verify_glb.py` compares re-imported mesh vertices as well as bones (expect `MESHERR 0.0`).

Unity note: a clip animates only its own morph weights. States must reset unanimated properties
(Animator "Write Defaults" on, or zero all blend shapes on state enter), otherwise the last
weight of the previous clip lingers. Disable per unit with `"correctiveSmooth": false`.

## Opt-in hook extensions (inferno, 2026-10-10)

Listed in a unit's `"extensions"`. Each one reads only its own config key, so other units build unchanged.

- **`ext/inferno_whipchain.py`, `"whipChain"`**: an articulated whip. `{"parent": "RightHand", "prop": "whip",
  "bones": 10, "grip": 0.12, "gripBlend": 0.10, "radius": 0.09}` adds `Whip_00..NN`, cut at equal arc lengths
  along the named prop's `segments` polyline (hand end first), each bone parented to the one before. It hooks in
  three places:
  - after_skin: creates the bones and their vertex groups.
  - after_pose: the chain rides the hand rigidly in every frame.
  - before_keys: the chain is re-derived after silhouetteRefine's propAim. Hand-rigid vertices within `radius` of
    the polyline move onto hat weights over the bone midpoints, eased off the hand over `gripBlend`. The bones go on
    the keyed free-bone list. The build fails if no vertex moves.

  Clip motion (the forward lash, the death fling) comes from patch-lane `keyRotations` on `Whip_*`. Used by
  h3_pit_fiend and h3_pit_lord.
- **`ext/floater_fix.py`, `"floaterFix"` per-piece options** (list the extension last), added to the existing
  reweight / `"bone"` modes:
  - `"from": "<bone>"`: picks, among the vertices at `point`, the copy whose dominant weight is that bone. A cut
    sliver shares every position with the surface it was cut from, so the point alone can land on the body and trip
    `maxVerts`.
  - `"delete": true`: removes the piece (floaters.py `fix: deleteIsland`, debris such as a Meshy segment broken off
    a whip). Deletions run after every reweight, in one bmesh pass, so the other points still resolve. The same
    fail-closed point and `maxVerts` checks apply.
  - `"weights": "vertex"`: each piece vertex copies the weights of its nearest host vertex. A host is outside the
    piece and not dominated by any of the piece's dominant bones. Use it for seam slivers that sit on a joint
    blend, such as a tail root or wing root, where the k-nearest mean still opens a gap. Fails closed if any host is
    farther than `maxHostDist` (default 0.03).
  - `"stage": "before_keys"` (per piece, or on `floaterFix` as the default): resolves after the other extensions'
    `before_keys` claims. Examples: the whip chain's tail and whip weights, wing_mesh_scale, and wing_chain's wing
    ownership. A sliver those claims create does not exist yet at `after_skin`. Pieces are dominated by chain bones
    there, so name them with `"from"`. `"delete"` is refused at this stage. List `floater_fix` after the
    extensions it repairs.

  Take points from `floaters.py` `fixPoint` (Blender Z-up). Prefer a vertex with no coincident copy outside the
  piece.

## Run order

```
bash tools/homm3_def_retarget/run_unit.sh <unit>               # build, render, measure, export GLB
RENDER_ONLY=1 bash tools/homm3_def_retarget/run_unit.sh <unit> # re-render / re-export an existing build
blender -b --factory-startup -P tools/homm3_def_retarget/verify_glb.py -- <blend> <glb> <out.json>
python tools/homm3_def_retarget/keysheet.py <unit>             # key-frame comparison sheet
```

`OUT_TAG` / `CFG_OVERRIDE` run a config variant into a side-by-side output folder.
Outputs: `artifacts/homm3_def_retarget/<unit>/` — `<unit>_def_retarget.glb`, the `.blend`,
`<unit>_compare.mp4/.gif`, `keyframes_sheet.png`, `metrics.json`, `glb_verify.json`.

## Known limits

- Body pose is only as good as the capture. Deaths the DEF shows as dust or sparks are
  approximated (rubble, shrink); the golem's rubble is scattered wider than the DEF's heap.
- Naga Move IoU fell (0.65 → 0.46 on the base Naga) because the tail now stretches out and
  does not exactly match the DEF tail's length and direction; the move reads much better by eye.
- High Naga / Naga Queen: the extra arm pairs are not rigged; a lower hand fused to the coil
  can float for a few Move frames. Their reels still carry ~11k / ~20k edges >2x.
- Genie arms are freer but still read close to the body at sprite size.
- Sprite-baked effects (lightning, sparks, the genie lamp) are not part of the mesh — Unity work.
- The gremlin flail chain is rigid, so the ball reaches the sprite's direction but not always
  its distance.
