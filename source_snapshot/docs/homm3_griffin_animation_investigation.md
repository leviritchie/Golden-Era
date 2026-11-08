# Griffin Animation Investigation

Status: 2026-10-05 full-body repair delivered for all three griffins and frozen
into `castle_griffin_slice_v1` (see "Full-Body Repair, 2026-10-05"); the base
griffin's idle was then refit upright (see "Upright Idle Pass, 2026-10-05", b17),
re-frozen in the same slice and built, not deployed. The
2026-10-04 sections below are the diagnostic that led to it. User-visible checks
remain in `docs/ingame_check_queue.md` only.

## Report And Installed Identity

The user reports that the animation is completely wrong, including idle, in both
battle and recruitment preview. This broadens the earlier rejection of the
four-legged sitting idle: the correction must preserve the authentic HoMM3 pose,
not substitute a convenient quadruped stance.

Direct SHA-256 readback from the active Golden Era
`BepInEx/plugins/OfflineUnlockMod/homm3_bundles` directory:

| Bundle | SHA-256 |
|---|---|
| `custom_units_castle_h3_griffin` | `63b0b9c5679dff9823e5f603818fc2b910dc030096be25a711cec05ec40052f1` |
| `custom_units_castle_h3_royal_griffin` | `542f9836a31cf8bb5009e61e6156cec10384ff21afb62ff4722791378e9ac905` |
| `custom_units_castle_h3_battle_griffin` | `37240020ec408c86200f7671f1babfdc523c086aeb0ec2165213247410981a8a` |

These match the rejected `14ab695470` sitting-pose shipment recorded in the
check queue. The current installed files are not the later local rearing-pose
candidate. This is installed-byte evidence, not a capture of the loaded game
objects.

The manifest is `tools/homm3_import/homm3_units_manifest.json`. Each griffin SID
has its own bundle and owned-skinned prefab. Static Unity preparation maps the
stock controller's Idle motion to the custom `Unit_Idle.anim`; the pose keys are
asset-owned while state selection and transitions retain the stock controller.
The shared battle/recruit symptom is consistent with this asset path, but no
runtime capture proved which prefab was loaded in recruitment.

## Existing Unfinished Repair

Preserve the pre-existing edits in `tools/homm3_def_retarget/units/h3_griffin.json`,
`h3_royal_griffin.json`, and `tools/homm3_glb_patch/patch_glb.py`. They remove the
four-legged idle and add a rearing-body adjustment plus per-frame forelimb
rotation tables. Scratch evidence is under
`V:/olden_port_work/units_rearing_forelimbs/`; its `RESUME.txt` records a paused
repair, not authorization or proof of delivery.

The base griffin's recorded rebuild completed the Blender-free delivery chain
and its numerical gates. That does not prove appearance, completeness of the
other griffins, bundle build, installation, or gameplay acceptance. Intermediate
patch/ground/rekey hashes differ by design; validate their links rather than
comparing every intermediate hash directly to the final GLB.

The focused patch-contract check for base, royal, and battle griffin took about
1.7 seconds. Base passes. Royal fails because its current patch configuration
was edited after its GLB was patched; it needs re-delivery, not a waived check.
Battle still declares the rejected 55-degree sit and planted forelegs; its
separate forelimb table is not integrated. Its validator pass only establishes
that the old configuration and GLB match. The aggregate command fails.
Peak RAM/VRAM was not measured for this existing CPU-side validator; no new
pipeline stage or acceptance gate was added.

The existing `boards/h3_griffin_g02_idle.png` is a cropped forelimb diagnostic
with a per-frame torso shift. It cannot establish the full body's stance,
head/wing proportions, fixed-camera trajectory, or runtime orientation. Full
pose comparison is required before deciding whether this repair is deliverable.

Independent source review also found that the rotation table pins its bytes but
does not provide a complete reproducible link to the exact DEF plates, manual
annotations, fit command/report, and fitting-code version. The endpoint fit
addresses the forelimbs; it is not authority for the broader authored body and
wing pose. Preserve this candidate as an unfinished repair, not a validated
full-animation replacement.

For base griffin Idle, the table has ten varying Arm offsets per side, but each
ForeArm and Hand has just two identical quaternion offsets. Those channels add
no independent local elbow/wrist articulation over Idle. Their world motion can
still inherit upstream joint motion; this observation alone does not prove a
mismatch to the DEF, but it limits what the existing correction accomplishes.

## Full-Pose Diagnostic

The idle-only GPU comparison is
`V:/olden_port_work/griffin_animation_investigation/griffin_full_pose_comparison.png`,
with input hashes, camera, sample times, embedded installed patch metadata, and
resource measurements in the adjacent `.json` report. It compares authentic DEF,
the installed-source pin `0d2b415e...`, and the local canonical candidate
`25fbbdcc...`. Both GLBs share the same camera, scale, and offset; there is no
per-frame root/torso shift. The installed-source metadata explicitly confirms
the 55-degree body lean and planted foreleg operation from the rejected sit.

The readable view is `griffin_full_pose_comparison_tight.png` in that same
scratch folder. Its one-shot `tight_crop_griffin_snapshot.py` helper applies
one common crop to all panels without resampling or realigning them; the report
records the bounds and helper path. The final helper run took 4.4 seconds
including Python startup; its peak host/GPU memory was not separately measured.
The helper is diagnostic scratch, not a production tool or acceptance gate.

Render time was 10.972 seconds on the RTX 5070 Ti, with peak CUDA memory of
111.3 MiB allocated / 122.0 MiB reserved. Host peak RAM was not measured.
This is one static idle sample, not continuous-motion, Unity-import, runtime,
or gameplay proof. Visual inspection shows that the candidate restores a raised
forelimb but still differs substantially from the DEF's head/wing silhouette.
The forelimb-only correction is not accepted as a complete authentic idle.

## Runtime Boundary

No active game process was found by the bounded process-name check. The installed
live-probe status file is dated 2026-10-03 and is not current runtime evidence;
no live-probe tools are exposed to this chat. No optional diagnostic flag was
enabled, no volatile runtime write was attempted, and the game was not launched.

The shared symptom makes the delivered pose/bind the first investigation target.
It does not, on its own, prove a controller, skin, or runtime-transform cause.

## Acceptance Boundary

Review the actual full pose and motion against the authentic DEF plates: idle,
mouseover, move start, flight, move end, hit, defence, attack, and death. A
candidate must preserve the rearing idle, articulated forelimbs, intended wing
fold, planted hind feet, and coherent transitions without hiding errors through
per-frame camera shifts. Numerical and provenance gates remain required but
are not visual acceptance. Only a new verified bundle shipment belongs in an
open check-queue row; this diagnostic does not create one.

## Full-Body Repair, 2026-10-05

Root causes of "completely wrong, including the idle":

- The installed build (`14ab695470`) replaced the DEF's two-legged rampant idle
  with a four-legged cat sit, and every ground clip inherited that stance.
- The later local candidate (v4: `sitRepose` + forelimb table) leaned the body
  about 45 degrees with the wings over the head. Only the forelegs were fitted.
- The v4 GLBs hold Spine/Spine2/Shoulder/ForeArm/Hand/Wing_01 as 2-key static
  channels. A table on the channel's own grid cannot articulate them per frame,
  so the elbow, wrist, upper spine and inner wing stayed frozen on Idle.

What changed (patch lane, `fleet_rebuild.py --from-base`):

- Op 3 on each griffin: a `keyRotations` body table
  (`tools/homm3_glb_patch/key_rotations/h3_*griffin_body.json`). It holds
  per-DEF-frame local offsets on the whole skeleton. They come from one GPU fit
  to every DEF plate of every clip (silhouette inside/cover, colour regions,
  hand-placed beak/head/thigh/tail/wing/claw/wrist keypoints, hind feet planted,
  wing mirror symmetry, a skin-stretch penalty) under one fixed camera. There is
  no per-frame shift.
- DEF frames that are pixel-identical to idle frame 0 take the fitted idle
  frame-0 pose exactly. Unit_Move keeps the v4 wing beat, because the fitted
  wings fell under the 60 degree wing-swing floor.
- New op key `regrid: true` (`docs/homm3_glb_patch_lane.md`): sparse channels
  are resampled onto the table's grid, so their offsets survive. Unit_Move is
  excluded because it stays on the densify stride.
- The royal and battle fits pin the view to the board camera (config yaw -100,
  no elevation). A free camera had drifted to a 28 degree low view, fitted
  upright poses as fallen, and delivered a death that never fell. Death frames
  3+ relax the body regulariser so the body can tip over.
- The battle griffin's rejected 55 degree sit is replaced with `sitRepose` 20 +
  its forelimb table + op 3. Its fit-only intermediate missed the stretch gate
  by 5 edges. The delivered spec passes it (5876 -> 5532 edges over 2x).
- The royal's idle frame 0 and its anchors are eased 15% toward v4 to satisfy
  the worst-edge rule (11.773 against an 11.807 cap).

Boards (full body, fixed camera, idle retimed x3.2 as delivered; DEF | delivered,
every clip, idle first): `V:/olden_port_work/griffin_repair/board_h3_griffin.png`,
`board_h3_royal_griffin.png`, `board_h3_battle_griffin.png`, with per-clip
strips `fb_*` (griffin), `rb_*`/`rs_*` (royal), and `bb_*`/`bs_*` (battle).

Judged match: on all three, idle, mouseover, hit, defence, attack and death follow
the DEF. The upright rampant stand has the head forward, a raised articulated
talon, planted hind feet and wings folded behind. Defence raises and spreads the
wings, attack lunges, and death falls flat by frames 7-8.

Known residuals:

- move start 2-3 and move end 1-2 are more hunched than the DEF.
- There is a one-frame thin wing on attack 6-7.
- Some mouseover/hit frames fan the wing.
- Death 4-5 stays upright where the DEF twists.
- Flight uses the v4 beat.
- The Meshy wings are larger and lighter or darker than the sprites.

`validate_homm3_glb_patch_contract.py --unit` passes for all three SIDs in about
0.5 s each.

## Upright Idle Pass, 2026-10-05

After the b5 install, the user sent the base griffin's idle back: it read as a
hunched crouch with a dark wing fan over the back, where the DEF stands tall on
its hind legs with the wings folded behind.

Measured on idle frame 0 under the board/game view (yaw -100, no elevation),
silhouette w/h against the DEF frame's alpha bbox:

| Build | w/h, frame 0 | w/h, mean | Wing top px (DEF 182) |
| --- | --- | --- | --- |
| DEF | 0.854 | 0.826 | 182 |
| b5 (installed) | 1.031 | 1.005 | 189 |
| b17 | 0.840 | 0.816 | 182 |

Causes:

- The b5 fit camera had drifted to yaw -108, elev -9.
- The CS stretch gate then eased the fitted idle toward v4. Easing a folded
  wing chain unfolds it into the fan.
- The upright fold costs about 20 edges newly past 2x per CS target. Most of
  them are at the wing roots and the left arm. A plain squared stretch penalty
  never saw them.

Fix (b17):

- The fit is pinned to the board view and adds two new `posefit.py` terms:
  `--w-ext` (silhouette extents) and `--w-wing-in` (wing on DEF wing pixels).
- `--w-gate` is a hinge on edges that pass 1.85x where the base stays at or
  under 2x, the same shape as the gate.
- With these terms the gate does not ease the idle at all.
- Idle, mouseover and move end are refit. The anchor frames are re-copied from
  the new idle.
- Hit, defence, attack, move start, move and death keep b5.
- The gate loop never eases the death's fallen frames 6-8, so the death still
  falls flat.
- `fleet_rebuild --from-base` passes, including the ground check that failed on
  b6: MoveEnd Hips at entry.

Board: `V:/olden_port_work/griffin_repair/board_h3_griffin_b17.png`. Comparison
at the `idle0_three.png` scale: `idle0_before_after.png`.

Residuals:

- Mouseover 1-6 still fans the wing partly. The gate eased frames 2-3 to 61%.
- Move end 1-2 stays hunched, as in b5.
- The head sits a little lower than the DEF's raised head.
- Royal and battle are unchanged. The same `--w-gate` recipe is the cheap next
  step for their squat torsos.


## Folded-wing ground mesh (s1, 2026-10-05)

The user approved a folded-wing ground mesh first, with a flight-mesh swap to
follow. Stage 1 replaces b17.

- Source mesh: `artifacts/meshy_downloads/h3_griffin_folded_smartrigged.glb`,
  from Meshy, 30 credits. `units/h3_griffin.json` selects it through a new
  `sourceMesh` field, which `run_unit.sh` reads. The order is `MESH_OVERRIDE`,
  then `sourceMesh`, then the default. The folded variant config has been merged
  into the unit config and removed.
- Identity: the `identity_reviews.json` h3_griffin entry carries
  `defRetargetMesh` (sha 0a3b5f46...).
- Floater fix: the wing exclude box z went from 0.5 to 0.45. That drops the 13
  Spine1 vertices that rode RightWing. The scan now shows 0 high, 0 medium and
  1 low.
- Patch: one keyRotations table, `h3_griffin_folded_body.json`. It comes from a
  board-view fit at yaw -40, with scale and offset fixed and the wing
  regulariser at 8.
  - The idle is held at the approved build pose.
  - The Move wing beat is set at +/-72 degrees, and the Move offsets are
    low-passed to DC plus the first harmonic, which passes the jitter gate.
  - In the gate loop, death frames 6-8 are frozen, and the Move body is eased
    as a whole, to 0.26.
- `fleet_rebuild --from-base` passes with no gate faults. The slice is
  `castle_griffin_slice_v1`, repinned.
- Boards: `V:/olden_port_work/griffin_folded/boards/board_s1_yaw-40.png` and
  `board_s1_yaw-100.png`.

Known: Move, MoveStart and MoveEnd keep a near-upright body with a rigid-wing
beat. Stage 2 replaces them with a spread-wing flight body.
