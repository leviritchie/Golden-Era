# Brief: DEF-retarget a faction's units (parallel agents)

Goal: every unit in your faction gets a GLB with one animation per HoMM3 DEF clip on its Meshy
mesh, following the Tower pipeline in this folder. Read `README.md` here first; the Tower configs
in `units/` are worked examples (`h3_gremlin*` flail, `h3_mage*` staff props, `h3_giant*`
colour-gated bolt, `h3_gargoyle*` wings + shatter death, `h3_genie*` floating + shrink death +
armCut, `h3_naga*` articulated tail, `h3_colossus` borrowed idle, `h3_golem` shatter).

## Inputs per unit
- Mesh: `artifacts/meshy_downloads/<unit>_smartrigged.glb` (UniRig weights are junk; layout is a usable seed).
- Capture + DEF frames: `artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/runs/<unit>/linked_master/`
  (`capture/capture/raw_capture.npz`, `master_sequence/master_sequence.json`, whose frames list the DEF PNGs).
- Units with no mesh or no capture: record them as blocked in your report; do not invent inputs,
  do not make paid Meshy calls.

## Procedure per unit
1. Look at the DEF (contact sheet of groups 02/00/12/15/05) and the mesh (gridded front/side/top
   renders) before configuring. Note body plan, held props, wings, tails, death style.
2. Seed joints: `blender -b --factory-startup -P auto_joints.py -- <glb> <seed.json>`; overlay the
   skeleton on the mesh and hand-fix wrong seeds (wings taken for arms, arms up a blade, missing legs).
3. Write `units/<unit>.json` (joints + only the options the unit needs).
4. `bash tools/homm3_def_retarget/run_unit.sh <unit>` (build, sprite-camera renders, metrics, GLB).
5. REVIEW AT HIGH RESOLUTION: `bash tools/homm3_def_retarget/review_unit.sh <unit>` and look at the
   `artifacts/homm3_def_retarget/<unit>/review/pair_*.png` images (768 px, cyan = edges >2x,
   yellow = >1.5x), at least the worst-stretch frames and one per clip. Sprite-size sheets hide
   broken geometry; the user has asked that review be done at this resolution. Also check the
   Idle and Move loops close smoothly (metrics.json "loops").
6. Iterate on config (and extensions) until the review renders look plausible, then run
   `verify_glb.py` (must print VERIFY OK).

## Learnings that apply everywhere
- Retarget uses capture joint *directions* only; `pred_rot6d` is unreliable, bone lengths vary 40%.
- Held props (staffs, weapons, bolts, blades, shields) must be cut free and bound rigidly (`props`);
  use `silhouetteRefine.propAim` to swing them to the DEF (the capture has no wrist twist).
- Non-humanoids: `grounding:false` for floaters; `wings`; `tail`; `silhouetteRefine` with dx/dy/roll.
- Deaths the DEF shows as rubble/dust: `shatter`; vanishing into an object: `shrinkOut`.
- Fused Meshy geometry (sleeves on robes, arms on chests, blades on coils) tears when parts move
  apart: cut it (`sleeve`, `armCut`, `props`, `metalBlades`), and split straddling triangles to one side.
- Loops: Idle and Move close on their first pose automatically; check the seam report.
- Weight noise shows up as triangle shards only at high resolution; `smoothPasses` did NOT fix the
  Gremlin's robe (its sleeve cut box reached into the robe sides) — check what a cut region really
  contains before trusting it (paint ownership, see Tower debugging in README).
- Measure, then look. Edge-stretch totals can go up when a real fix separates a fused part.

## Counting and reporting: the full roster
Every faction has 21 units (7 lines x base / upgrade / alternate upgrade). Report against all 21,
never "all N with inputs". `python tools/homm3_def_retarget/roster_status.py <faction>` maps each
roster slot to its pipeline id (h3_*, hota_<faction>_*, toa_*, ...) and gives its status (done /
stale / built / config / ready / hand / no-mesh ...). Alternate upgrades are real units with their
own meshes and captures (e.g. Stronghold's toa_* units), not aliases.
Meshes that were missing from meshy_downloads were installed from the fleet's canonical meshes
(`artifacts/meshy_downloads/meshy7_missing/<unit>/mesh.glb`) with `install_mesh.py`; check the
unit's DEF against its mesh before building, and report a wrong mesh rather than working around it.

## Units with no usable mocap: hand-keyed joints
Units whose only capture is under `runs/<unit>/remaining_forced_*` (forced onto a mismatched
skeleton: beholder, nereid, cannon, automatons, ...) are animated by hand, not from that capture:
1. `python tools/homm3_def_retarget/hand_stub.py <unit>` writes a MOTIONLESS stand-in capture and
   the forced run's clip layout into `runs/<unit>/linked_master/` (labelled `"mocap": false`).
2. In the unit config add `"extensions": ["hand_keys"]` and `"handKeys"`: per clip, keyframes of
   bone rotations (XYZ degrees in the bone's rest frame) and an optional `root` offset, chosen by
   looking at that clip's DEF frames. See the docstring of `ext/hand_keys.py`.
3. Build/review/verify as usual; `silhouetteRefine` can still fit offsets/lean to the DEF.
Non-humanoid bodies (a beholder's eye stalks, a cannon) add their own bone chains in a faction hook
before `after_pose`, then key them the same way.

## Rules for sharing this folder (several agents run at once)
- Do NOT edit shared scripts (`build_unit.py`, `surface_weights.py`, `run_unit.sh`, ...) for faction
  needs. Put new behaviour in `ext/<faction>_<name>.py` with hook functions (`after_skin`,
  `after_pose`, `before_keys`, see `run_hooks` in build_unit.py) and list it in the unit's
  `"extensions"`. A genuine shared bug fix is allowed only if it is backward-compatible and tiny;
  mention it in your report.
- Only touch your faction's `units/*.json`, your `ext/` modules, and your units' artifact folders.
- Run at most ONE Blender process at a time, and before starting EACH one run
  `python tools/homm3_def_retarget/memgate.py --wait 6`. If it prints MEMGATE FULL, do not start the
  process: update your handoff, stop, and report "paused: memory full" to the lead. Never leave a
  background queue/loop script running when you stop.
- Commit your own files with explicit paths (`git add tools/homm3_def_retarget/units/<unit>.json ...`),
  never `git add -A`; end the message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
  Do not push. Do not touch other agents' units.
- Label evidence honestly: these are generated artifacts, not Unity/runtime proof.

## Report back
Per unit: done / blocked (why); per-clip IoU and loop seams from metrics.json; the path of one
review pair that shows the unit at its worst; known remaining defects. Keep it short.
