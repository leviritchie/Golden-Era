# Mesh repair operator workflow

For bounded fleet work, use the repo skill
[homm3-mesh-repair](../.agents/skills/homm3-mesh-repair/SKILL.md). It owns compact
selection, selective regeneration decisions, saved-motion evidence packets and
individual-panel review. Its isolated pilot report is
`artifacts/homm3_mesh_repair_skill_pilot_v1/pilot_report.md`; candidate execution is
not final mesh-quality or game-delivery acceptance.

## Run an existing recipe

Work from the repository root. A job reuses saved mocap; it does not regenerate motion or install
anything in the game. Choose a manifest, not a directory of assorted previous experiments.

| Unit | Manifest under `tools/homm3_meshy_frame_pose/` | Current scope |
| --- | --- | --- |
| Archer | `archer_rest_fit_pilot.json` | Body fit and rigid crossbow attachment |
| Crossbowman | `crossbowman_meshy71_tpose_pilot.json` | Body fit only; weapon extraction unfinished |
| Wood elf | `wood_elf_rest_fit_pilot.json` | Body fit and rigid longbow attachment; string/contact cleanup remains |

```powershell
py -3 tools/homm3_meshy_frame_pose/fit_mesh_rest_pipeline.py --manifest tools/homm3_meshy_frame_pose/archer_rest_fit_pilot.json --units h3_archer --review
```

The command prints the output directory. Open `rest_overlay.png` and `keyframes.png` at full
resolution. Check joints inside their corresponding limbs in BOTH front and side views, followed
by idle, move, attack, shoot, and death. A provenance-valid registration is not proof of alignment.

When those stills are useful, replace `--review` with `--preview` for `animation_reel.gif`.
The reel uses a fixed review cadence, not game timing. Unchanged jobs are cached; recomputing
clears old previews. `report.json` names current inputs, outputs, and stage timings.

## Prepare a new unit

1. Locate the original textured mesh and its saved mocap unit run. Find the paired registration
   in `linked_master/idle0_registration.json` or the explicit corrected registration directory.
   The existing `homm3.static-bind-registration.v1` report works directly as `sourceReport`.
2. Inspect textured front AND side rest views. The current geometry fitter requires a Y-up
   T-pose biped with separated legs and extended arms. Do not test every old derivative when
   they all preserve the same unsuitable rest pose.
3. For an unsuitable source, choose a constructive next step: a genuinely applicable shared
   fitting adapter, or one authorized selective Meshy 7.1 T-pose candidate. Do not simply relabel
   an idle mesh as T-pose, trust its registered skeleton without looking, or stop at a refusal.
   Regeneration is a limited repair option, not the default for all 261 units. No T2 substitution.
4. Make one manifest and run the body-only `--review` first. Fix skeleton placement before
   spending time on skin weights or weapon orientation. Keep a comparison output directory.
5. If a prop is fused or misplaced, author its recipe using the inspection steps below. Then
   review the combined animation and produce the reel.

Authorized selective generation uses the existing reusable command:

```powershell
py -3 tools/homm3_meshy_frame_pose/generate_meshy71_repair_candidates.py generate --unit UNIT --variant t-pose --polycount 8000 --timeout-s 1800
```

Job fields: `unit`, `bodyPlan: "biped-tpose"`, `mesh`, `runDir`, `sourceReport`, `out`, and optional
`propAttachments`. Paths are repository-relative or absolute. `out` is a new candidate directory,
not the source directory. `runDir` must contain the saved linked-master capture and sequence.
Use `--units` to run one unit or a small representative batch, not the full roster during tuning.

## Author a prop recipe

Use `inspect_prop_recipe.py` instead of inventing coordinate-probe scripts:

```powershell
py -3 tools/homm3_meshy_frame_pose/inspect_prop_recipe.py --mesh MESH.glb --out INSPECTION_DIR
py -3 tools/homm3_meshy_frame_pose/inspect_prop_recipe.py --mesh MESH.glb --out INSPECTION_DIR --pick 90:320:410 0:400:360
```

The first command writes individual 600x700 textured views with pixel rulers. For small or fused
regions, add `--panel-scale 4` to write 2400x2800 views; use the same scale when supplying pixel
picks. The second returns
the actual visible surface point and face for each `yaw:x:y`. Use the original individual PNG,
not a scaled contact sheet. A background pick is an error, not a nearest-vertex guess. Inspect
several angles; one view can hide the stock or show the quiver in front of the weapon.

Build a `prop_attachment.v1` JSON recipe, using an existing recipe for FIELD STRUCTURE only:

1. Copy `sourceMeshSha256` from `inspection.json`.
2. Put foreground seed capsules on each visible part of the weapon: grip/stock and BOTH limbs.
   Seed nearby clothing, quiver, and body as background. Bounds include the prop but exclude
   distant body geometry. Coordinates are specific to this mesh; never copy another unit's.
3. Set `sourceGrip` on the handle. `sourceForward/sourceUp` describe its current orientation;
   `targetForward/targetUp` describe the desired orientation in the target mesh REST pose.
   `targetOffset` is relative to the named bone's rest head, not its animated shooting location.
4. Verify the cut BEFORE moving it:

```powershell
py -3 tools/homm3_meshy_frame_pose/inspect_prop_recipe.py --mesh MESH.glb --out INSPECTION_DIR --recipe RECIPE.json
```

Inspect `prop0_yaw*.png` and `body_yaw*.png`. The prop must be complete, clothing must remain on
the body, and no weapon remainder should still be fused to the body. A connected-component count
or an attractive shooting silhouette alone cannot establish correct extraction. Adjust seeds,
not the whole rig, when the cut is wrong. Do not render a full reel for each seed attempt.

Then add `propAttachments` to the job and run `--review`. Check grip placement and weapon direction
in idle AND shooting. The shared repair preserves textured triangles, duplicates contact vertices,
rotates authored normals, and gives the prop rigid bone ownership. It does not fill missing
interior surfaces, close fingers, or solve a second-hand grip.

When a fused source prop cannot be isolated cleanly, do not feed the contaminated cut into the
body repair. A standalone Meshy 7.1 prop attempt is available through
`generate_meshy71_prop_candidate.py`, but it is still an unbound geometry candidate:

```powershell
py -3 tools/homm3_meshy_frame_pose/generate_meshy71_prop_candidate.py start `
  --unit UNIT --prop PROP --input ISOLATED_REFERENCE.png --out PROP_CANDIDATE
py -3 tools/homm3_meshy_frame_pose/generate_meshy71_prop_candidate.py poll `
  --out PROP_CANDIDATE
```

The input is copied and hashed before submission, task IDs are persisted before polling, and the
result must be rejected if it reconstructs adjacent body/cloth/hand geometry. This command never
merges the prop into a body or silently changes an existing repair candidate.

## Finish the iteration

```powershell
py -3 -m unittest tools.homm3_meshy_frame_pose.test_mesh_rest_fit tools.homm3_meshy_frame_pose.test_rest_retarget tools.homm3_meshy_frame_pose.test_prop_attachment tools.homm3_meshy_frame_pose.test_fit_mesh_rest_pipeline tools.homm3_meshy_frame_pose.test_reel_meshy71_candidate tools.homm3_meshy_frame_pose.test_inspect_prop_recipe tools.homm3_meshy_frame_pose.test_wood_elf_recipe
```

Deliver the current reel, rest overlay, manifest, and specific remaining visual defects.
`fitted_bind.glb` is static mesh/skin; `retargeted_motion.npz` contains animation transforms.
Do not describe either as an installed game asset. Keep unsuccessful experiments out of the
default manifest. Record reusable lessons in focused docs rather than adding another fallback.

Details: [fitting and retargeting](homm3_mesh_rest_fit_pipeline.md),
[crossbowman trial](homm3_crossbowman_luna_trial.md), [wood elf result](homm3_wood_elf_repair.md).
