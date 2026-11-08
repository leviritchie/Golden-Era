# HoMM3 Semantic Hybrid Pose Experiment

This directory contains the source-owned notebook runtime for experimenting with fitting a skinned 3D unit to HoMM3 battle-sprite frames. The main experiment is the Roc semantic hybrid pilot, but the asset picker can expose other discovered unit and animation inventories through the same runtime.

The experiment is an optimizer and preview tool. It is not an automatic rigging system, not a replacement for authored sprite landmarks, and not proof that a result is ready for Olden Era battle delivery.

## What It Experiments With

The notebook can compare a rendered mesh pose against each source frame using several independent or combined signals:

- SigLIP2 image embeddings for semantic image similarity.
- Optional dense patch-token feature matching with a constrained local window and positional cost.
- Dense-feature ablations for global SigLIP2, dense SigLIP2, dense DINO-family models such as DINOv3, and global+dense combinations.
- Optional multiple embedding layers, averaged per layer rather than concatenated.
- Optional multiview semantic scoring using configured camera angles and elevations.
- Optional subject cropping and padding before semantic embedding.
- Worker-side geometry scoring using depth or chroma/silhouette data.
- Asymmetric foreground/background zone penalties.
- Silhouette edge emphasis.
- A reverse-profile objective for the opposite side of the unit.
- Optional text-image similarity, including a positive prompt.
- Optional negative text similarity, which penalizes similarity to an unwanted prompt.
- Local GPU anatomical-part detection using Grounding DINO.
- Anatomical feature alignment based on detected part centers and extents.
- Coarse and fine bone-angle search.
- Single-bone coordinate descent, block-coordinate search, and joint beam search.
- Dependency, reverse-dependency, alphabetical, explicit, or branch-walk bone order.
- Search-axis selection and optional bone-roll exclusion.
- Near-bone refinement after a primary bone pass.
- Frame-to-frame pose seeding for animation continuity.
- Optional global clip fitting that evaluates every accepted proposal against the complete frame set plus robust velocity, acceleration, contact-stability, and loop penalties.
- Optional rotate-only IK targets, automatic target loading, and pixel-space target search.
- Camera/profile detection and optional source-frame mesh orientation handling.
- Live RGB and anatomical feature previews during optimization.
- Full-frame animation delivery renders and JSON history reports.

The individual terms are deliberately explicit. A disabled term is not silently substituted with another objective.

## Important Proof Boundary

The experiment can establish that source files, generated fit outputs, and preview renders were produced. It does not by itself establish:

- that sprite landmarks are authored correctly;
- that the mesh has an owned skeleton and owned skin weights;
- that a preview pose reads correctly to a human reviewer;
- that Unity imported the mesh and clips correctly;
- that an Olden Era battle prefab uses the result;
- that the deployed game displays the unit correctly at runtime.

Use the following labels when recording results:

1. `source/static validated`: configuration and Python source are coherent.
2. `generated artifact validated`: fit files, previews, and reports were written and inspected.
3. `build target proven`: the downstream asset/build path accepted the artifact.
4. `deployed payload proven`: the built payload was installed and read back.
5. `startup smoke proven`: the game started with the payload.
6. `runtime behavior proven`: the intended runtime path was exercised.
7. `user-visible gameplay proven`: a human observed the requested battle behavior.

## Source Layout

The notebook-facing entry point is `roc_semantic_hybrid_experiment.py`. It reads neighboring source files and executes them into one shared namespace so the Blender worker, optimizer state, preview state, and helper functions remain available to the notebook.

| File | Responsibility |
| --- | --- |
| `roc_semantic_hybrid_experiment.py` | `RocHybridConfig`, `initialize`, experiment summary, worker shutdown, and public run functions. |
| `roc_semantic_hybrid_widgets.py` | Asset discovery and picker support for unit/animation choices. |
| `roc_semantic_hybrid_setup.py` | Input paths, depth preparation, camera/profile setup, bone hierarchy, range setup, and anatomical target detection. |
| `roc_semantic_hybrid_solver_body.py` | Scoring terms, semantic embedding setup, request construction, IK, optimization strategies, and live previews. |
| `roc_semantic_hybrid_delivery.py` | Full-frame loop, final renders, per-frame history, and `report.json`. |
| `roc_semantic_hybrid_report.py` | Pairwise semantic report over already rendered target/mesh frame pairs. |
| `roc_anatomical_boxes.py` | CUDA-only Grounding DINO detection, feature selection, alignment, overlays, and JSON box output. |
| `roc_semantic_embedding_match.py` | SigLIP2 image/text embedding and cosine comparison support. |
| `dense_semantic_features.py` | CUDA-only SigLIP2/DINO-family patch-token extraction and local spatial scoring. |
| `roc_temporal_clip_optimizer.py` | Model-free global clip objective, robust temporal terms, and black-box coordinate proposals. |
| `roc_chroma_match_worker.py` | Persistent Blender-side rendering and geometry scoring worker. |

`roc_semantic_hybrid_solver_body.py` and the other source fragments are not intended to be run directly. They depend on the namespace assembled by `initialize`.

## Basic Notebook Usage

From a notebook located at the repository root or with the tool directory on `sys.path`:

```python
from tools.homm3_silhouette_pose_fit.roc_semantic_hybrid_experiment import (
    RocHybridConfig,
    initialize,
    run_frame0_pilot,
    run_clip_pilot,
    run_full_animation,
    run_semantic_report,
)

CONFIG = RocHybridConfig(
    root=Path(r"V:/Games/Olden Era Playtest Tweak"),
    src_glb=Path(r"C:/path/to/owned_or_transition_master.glb"),
    unit_name="roc",
    animation_name="move_g0",
    anatomical_boxes_enabled=True,
    show_anatomical_boxes=True,
)

experiment = initialize(CONFIG)
experiment.summary()
```

The exact import form depends on how the notebook was opened. The source loader resolves tool files relative to `roc_semantic_hybrid_experiment.py`, so the tool directory does not need to be the current working directory.

The initialization sequence is:

1. Close the previous active experiment, if one exists.
2. Create the shared runtime namespace.
3. Load configuration values into that namespace.
4. Prepare target/depth inputs.
5. Discover the mesh hierarchy and build bone ranges/order groups.
6. Start the persistent Blender worker.
7. Initialize anatomical target detection when enabled.
8. Initialize semantic embedding services when enabled.
9. Load the solver body.

The worker is persistent because repeatedly starting Blender for every trial would make coordinate descent impractical. Close it when finished:

```python
experiment.close()
```

If a notebook cell failed during initialization after source files were changed, restart the kernel or call `initialize` again. The anatomical helper is explicitly reloaded to avoid stale `sys.modules` state during repeated notebook initialization.

## Asset Picker

`roc_semantic_hybrid_widgets.py` discovers numbered source PNG frames and associated job metadata under the pose-pipeline artifact roots. It intentionally excludes derived directories such as `out_fit`, previews, renders, scratch directories, pseudo-rigs, and other generated products from source discovery.

An asset choice resolves:

- unit name and unit SID;
- animation name and choice ID;
- source-frame directory;
- isolated pilot directory;
- camera-fit path or provisional camera metadata;
- frame indices;
- default mesh, when job metadata provides one.

The picker lists authentic 12 fps lab DEF sequences. Ship choices are idle-leading. Each of those also appears as a motion-only diagnostic with idle prefix/suffix removed (`start_move_end` next to `idle_start_move_end`). Motion-only writes a separate `pilot_dir` and is not a delivery choice.

The Mesh dropdown is independent from the Unit and Animation dropdowns. A
unit change does not replace an explicitly selected mesh. `config_overrides()`
passes the resolved selected GLB as `src_glb`; worker initialization reports
the same resolved path and its SHA-256, and setup fails closed if Blender
reports a different mesh identity.

## Inputs And Preprocessing

`RocHybridConfig` resolves paths relative to `pilot_dir` unless an absolute path is supplied.

### Mesh

`src_glb` is the mesh loaded into Blender. The solver can search its discovered bones, but it does not create an owned bind or repair incorrect skin weights. A Mixamo or Meshy rig can therefore produce a useful diagnostic fit while remaining blocked as a delivery asset.

### Sprite frames

The normal target path is:

```text
<pilot_dir>/frames_src_shadow_culled/
```

The raw source path is retained separately as `frames_src`. Shadow culling removes the dark or partial shadow pass before matching. `FRAME_INDICES` selects which numbered frames are used.

### Depth

The configured `target_depth_dir` stores predicted depth inputs. Depth is a geometry subterm, not the only possible geometry objective. The worker can also use chroma/silhouette, zone, edge, reverse-profile, and anatomical information according to the request.

### Camera and profile

`camera_fit_path` normally points to `roc_sprite_camera_fit.json`. When profile detection is enabled, the setup can sample the source mesh to identify the side-profile basis. `mesh_orientation_mode` accepts `none` or `auto`; `none` preserves the selected mesh source frame rather than applying a guessed canonical rotation.

Generic picker choices may carry a `provisional_job_camera` rather than an
authoritative sprite fit. Those cameras are automatically calibrated against
frame 00 before searching when `auto_frame0_camera_fit=True`: the persistent
Blender worker renders the actual textured mesh, measures its visible alpha
bounds, and makes at most two bounded scale/center corrections. This uses the
visible skinned silhouette rather than imported object bounds, which avoids
unit-to-unit scale errors from helper geometry or loose rig bounds. The
controls are `frame0_fit_alpha_threshold`, `frame0_fit_margin`, and
`frame0_fit_passes`. Authoritative camera fits are never modified by this
calibration.

Action-camera parameters are separate from profile detection:

- `action_camera_angle_deg` controls the longitudinal action view relative to the detected side profile.
- `action_camera_elevation_deg` controls elevation.
- `profile_samples` controls profile sampling density.

## Score Architecture

The solver reports a normalized hybrid score made from the components that are enabled and have positive weights. The active terms are recorded in score details and in the full animation report.

### Semantic image score

When semantic scoring is enabled, the target and candidate images are embedded with `semantic_model_id`, normally `google/siglip2-base-patch16-512`. A candidate can be embedded at one or more layers. Layer cosines are computed independently and averaged; vectors are not concatenated across incompatible dimensions.

`semantic_pooling` selects the embedding pooling behavior. `semantic_subject_crop` optionally crops around the subject with `semantic_subject_padding_frac` padding.

With `semantic_multiview=True`, the candidate is rendered at the configured three angle/elevation pairs and combined with `semantic_view_weights`. The target remains the source sprite; the multiview candidate set reduces dependence on one potentially misleading camera.

### Dense semantic score

`semantic_dense_enabled=True` adds a separate spatial feature lane. `DenseFeatureScorer` runs the configured GPU vision tower once per target/candidate image pair, removes class/register prefix tokens, reshapes patch tokens into a grid, and compares each token against a bounded neighborhood at the same image location. `semantic_dense_position_weight` makes a displaced feature less attractive even when its content is similar. `semantic_dense_embedding_layers` selects one or more hidden layers; distances are averaged per layer, not concatenated.

The global image cosine and dense patch distance are intentionally separate controls. A useful first ablation is:

```python
# global SigLIP2 only
semantic_dense_enabled=False
hybrid_semantic_weight=0.25

# dense SigLIP2 only
semantic_dense_enabled=True
semantic_dense_model_id="google/siglip2-base-patch16-512"
semantic_dense_weight=1.0
hybrid_semantic_weight=0.0

# dense DINOv3 only
semantic_dense_model_id="facebook/dinov3-vits16-pretrain-lvd1689m"
semantic_dense_weight=1.0
hybrid_semantic_weight=0.0

# global + dense
hybrid_semantic_weight=0.25
semantic_dense_weight=0.75
```

The dense lane is CUDA-only, as is the existing semantic lane. It reuses the existing neutral-background and optional subject-crop preprocessing so the ablation changes the feature comparison rather than the image source.

The gated DINOv3 dense ablation is available through the notebook's
`USE_DINOV3_DENSE` toggle and the overnight runner's
`05b_dinov3_dense_only` variant. Authenticate through the process environment
(`HF_TOKEN` or `HUGGINGFACE_HUB_TOKEN`); do not place a Hugging Face token in
the notebook, source files, config JSON, or generated artifacts. A missing
token is a hard load error for that explicit variant, not a fallback to
SigLIP2.

That overnight `05b` path is the **old Blender hybrid**. GPU cascade has a
separate switch: `CASCADE_SCORE_MODE = 'dinov3_dense'` in
`roc_chromatic_single_bone_match.ipynb` (`GpuCascadeConfig.score_mode`).
Every cascade candidate is scored with gated DINOv3 patch grids only
(`1 - local-window dense distance`). Packed evals share one ViT microbatch
(`CASCADE_DENSE_SEMANTIC_BATCH_SIZE`) on GPU RGB; there is no CPU/PIL
round-trip and no per-sprite-frame encoder grouping. Raster scale `0`
derives an integer proxy scale that covers the processor input
(`ceil(224/96)=3` → 288×258 on the 96×86 proxy) so the camera aspect is
unchanged; the processor still square-resizes. ViT encode is fp16; L2 and
the local-window keep are fp32. Near-ties at
`joint_keep_min_improvement=1e-6` may flip versus a pure fp32 encoder.
Do not start with INT8. Silhouette, Huber depth, Lab chroma,
collision, unique occupancy, Adam root, the gradient ladder, IK, and
dynamic bone-order modes cannot mix. Discrete root hypotheses run only
when `CASCADE_ROOT_SEARCH_ENABLED` is True (notebook default False skips
the early whole-body spin). Profile camera init still uses silhouette IoU. `CURRENT_CASCADE_KEEP`
refuses any `score_mode` other than `'geometry'`, so this ablation cannot
ship. Default remains `'geometry'`. The adapter
`run_gpu_depth_fit_from_hybrid_config` zeros the geometry mix-ins when the
mode is on; it does not silently turn the gradient ladder off — set
`CASCADE_GRADIENT_LADDER_ENABLED = False` or validation fails. Need
`HF_TOKEN` and a painted albedo on the GLB. Do not treat this as a
replacement for `USE_DINOV3_DENSE` on `one_bone_depth`. That one-bone
toggle still mixes geometry with a dense extra term; it now encodes
targets and candidates on GPU RGB (`extract_layers_from_rgb_hwc`, same
packed helper as cascade, default ViT microbatch 8) and upsamples the
score raster with `chroma_scale` when dense is on even if Lab chroma is
~0. There is no PIL fallback for that dense path.

### DINOv3 autograd branch vectors

The opt-in DINOv3 autograd experiment is a separate cascade lane. It preserves
the float RGB graph through DINOv3 preprocessing and feature extraction, then
uses the complete clip gradient to propose one F x 3X trajectory for each
disjoint non-forking branch. One RMS magnitude normalizes the full trajectory;
candidate acceptance is scalar and atomic over the complete clip. DINOv3
activation graphs are released in two-frame backward microbatches. Exact
candidate selection and reporting stay on the established detached inference
path. Each branch visit tests the current trust radius and every descending
half step through the configured floor; a coarse overshoot is not logged as a
frozen branch. Results separately report exactly frozen joints and joints that
exceed one degree of serialized motion.

`run_dinov3_branch_vector_examples.py` is the reproducible three-clip runner.
It fails closed on input, model, configuration, or solver-source hash drift and
keeps geometry, legacy articulated search, root search, IK, smoothing, and
other proposal stages disabled. Validate its generated output with
`validate_dinov3_branch_vector_examples.py`. See
`docs/dinov3_autograd_branch_vector_examples.md` for commands, current results,
and the proof boundary. This lane remains outside `CURRENT_CASCADE_KEEP`.
The current three-clip result is a negative experiment: semantic scores improve
while motion coverage remains sparse or partial and pose fidelity is poor.
DINOv3-only scoring is not a production pose authority; use authored joints and
geometry first, with DINO only as a possible secondary term.

Joint search is one articulated walk with a per-frame unit step from the current keep score (`joint_adaptive_step_enabled`, keep-required). Scores are stretched with `joint_step_score_norm='logit_minmax'` (keep-required) before the 0.45/0.80 lerp: logit then min-max so a tight band near 1 still gives walk frames coarse rungs. Score at/above `joint_step_score_fine` (0.80) uses `fine_joint_step_deg` (2.5 degrees); at/below `joint_step_score_coarse` (0.45) uses `joint_step_deg` (15 degrees, times three rungs). Base, mid, fine, and branch rescue do not run in that mode. Log `gpu articulated adaptiveStep` and `gpu base skipped: joint_adaptive_step`. Old clip JSON with `raw` or a missing norm fails `CURRENT_CASCADE_KEEP`. Set `CASCADE_JOINT_ADAPTIVE_STEP_ENABLED = False` only to restore the old 15 then 5 then 2.5 degree ladder.

Idle wiggle on a still sprite is a keep-law issue, not a missing smoother.
Each frame independently keeps any probe that raises DINOv3 by more than
`1e-6`, even when the PNG barely changed. Physics smooth can hide the
same twitch; it does not explain it.

`joint_keep_still_sprite_lock` (default **off**, not a ship flag) copies the
previous frame's full pose onto frames whose consecutive target-PNG RGB MAD
is below `joint_keep_still_sprite_rgb_mad` (0.015). Angel
`idle_start_move_end` locked 14/28 plates (01–07, 21–27). Solved RGB MAD on
those holds went from ~0.018 without the lock to **0** with it: idle did
not move at all. Prefix copies frame 00 as a block. Suffix copies frame 20
(the first idle-return plate). That whole-pose copy is too coarse, and the
lock run was slower (~1016s vs ~870s unlocked). Runner:
`run_angel_dinov3_still_sprite_lock.py`. Keep the GIF; do not treat this as
delivery keep.

`joint_keep_sprite_change_gate` (default **off**, not a ship flag) uses the
sprite-to-sprite change map as an **allowance**, not as a score mix-in.
The first mix-in (`weight=1` subtracted from DINOv3) destroyed pose
quality: Angel `idle_start_move_end` elapsed **1177s**, reported score
**0.822** (unlocked/lock were ~0.960), idle consecutive solved RGB MAD
stayed ~0.019, and motion was damped (0.044→0.028). Keep that GIF under
`gpu_depth_fit_sprite_change_gate`. Do not mix RGB MAD into DINOv3.

The follow-up is a **veto** against the last accepted picture of the
**same** plate (`|probe[f] − committed[f]|`), with allowance
`|sprite[f] − sprite[f−1]|` plus `joint_keep_sprite_change_slack` (0).
A veto on **every** plate froze Angel frames 01–27 to one identical
picture (`gpu_depth_fit_sprite_change_step_veto`, 665s, score **0.913**,
idle 01–07 MAD 0.004, motion 08–20 MAD **0**, idle 21–27 MAD **0**).
Only frame 00 can move: it has no previous sprite, so excess is forced
to 0. The first joint step off bind changes more RGB than consecutive
sprites do, so later plates never leave bind.

The gate now vetoes **still sprites only** (consecutive target-PNG RGB
MAD `< 0.015`, same 14/28 Angel plates as still-lock). Walk plates keep
unconstrained DINOv3. After base and articulated, still plates are
seeded from the previous pose once so they are not left in bind. That
is not still-lock: later keeps on still plates may shimmer within the
sprite change map, and the pose is not re-copied after every keep.
Excess `> 1e-6` zeros that still probe's keep. Cannot mix with
still-lock. Requires RGB raster. Runner:
`run_angel_dinov3_sprite_change_gate.py` writes
`gpu_depth_fit_sprite_change_still_veto`. Angel `idle_start_move_end`
elapsed **817s**, score **0.956** (unlocked ~0.960). Consecutive solved
RGB MAD: idle 01–07 **0.0017** (unlocked 0.018, lock **0**), motion
08–20 **0.047** (unlocked 0.044, lock 0.047), idle 21–27 **0.0009**
(unlocked 0.020, lock **0**). Frames 02–07 match 01 and 22–27 match 21
(holds, not a 01–27 freeze). Walk plates each have a distinct picture.
Do not turn the notebook default on. Do not add this to
`CURRENT_CASCADE_KEEP`.

Cascade `live_preview=True` is a solver watch, not a single still. The
panel is a strip of sampled clip plates (idle, first motion, last motion,
last frame). Top row is the last finished method step. Bottom row is the
live step. A third row is amplified |now − previous| so ``base 1/2`` and
``base 2/2`` cannot look identical unless those plates did not move. The
caption is the round name. IPython id is ``gpu_depth_live_preview``; PNG
is ``gpu_depth_fit/preview/live_preview.png``. ``dinov3_dense`` uses RGB
occupancy and does not need VDA depth. Re-run config + GPU cells. Keep
`SIMPLE_DEPTH_LIVE_PREVIEW_SCALE = 1`; the watch pane is already shrunk.

### Geometry score

The persistent worker owns the render-side geometry score. Depending on `score_mode` and the configured controls, it can account for:

- predicted depth or chroma/silhouette agreement;
- silhouette/depth weight;
- blue-zone penalty for candidate-only pixels;
- red-zone penalty for target-only pixels;
- silhouette edge bonus;
- reverse-profile score and weight;
- target/candidate anatomical box comparison.

`hybrid_geometry_enabled` controls whether geometry participates. `hybrid_geometry_weight` is the current geometry weight; `hybrid_depth_weight` is retained as a compatibility alias for older notebook cells.

The zone penalties are asymmetric on purpose. Candidate-only mass and target-only mass represent different failure modes and can be penalized differently.

### Anatomical score

Anatomical detection is a local CUDA-only Grounding DINO lane. The fixed vocabulary currently includes head, beak, eye, neck, torso, shoulder, wing segments, wing tip, tail, leg segments, ankle, foot, and talon.

For each target-selected part:

- a matching candidate detection is scored from center displacement and box extent displacement;
- center and extent contributions use `anatomical_center_weight` and `anatomical_extent_weight`, normalized to their sum;
- a missing candidate detection receives distance `1.0` and score `0.0`;
- extra candidate detections do not change the target-defined score;
- duplicate detections for one part are reduced to the highest-confidence box.

The overall anatomical score is `1 - mean(distance)`. The candidate detector is restricted to target-detected part names, so a target detector miss cannot be recovered by an unrelated extra candidate label.

There are two anatomical controls with different meanings:

- `anatomical_part_weight` blends the anatomical score into the worker geometry score after candidate detection.
- `hybrid_anatomical_weight` adds the anatomical score as a separate hybrid component in `hybrid_score_details`.

Do not enable both merely because both names contain "weight". That double-counts anatomy through two separate paths. Use one ownership path for an experiment and record which one was selected.

`anatomical_boxes_enabled` enables detection and scoring. `show_anatomical_boxes` enables the colored-dot/legend preview and box artifacts. The current setup also exposes the preview automatically when anatomical scoring is enabled so active identification is not silently hidden.

### Text score

Positive text scoring embeds `semantic_text_prompt` and compares it with the candidate image embedding. Negative text scoring compares the candidate against `semantic_negative_text_prompt`; it is a penalty term, not a positive match. Each requires its corresponding enable flag, and a positive weight without the required enable flag fails validation.

### Hybrid combination

`hybrid_score_details` creates an explicit row for each active component, including its name, weight, normalized score, and raw value where applicable. The optimizer uses the resulting weighted score. It fails closed when a required component result is missing rather than silently treating a missing measurement as a good fit.

## Pose Search

### Global clip objective

`clip_optimization_enabled=True` changes the acceptance rule for a clip. The solver still uses coordinate proposals because Blender is a black box, but a proposal for frame `t` is accepted only when it improves the objective over all selected frames:

```text
mean(image_quality[t])
  - velocity_weight * robust_velocity
  - acceleration_weight * robust_acceleration
  - contact_weight * robust_contact_stability
  - loop_weight * loop_pose_mismatch
  - loop_velocity_weight * loop_velocity_mismatch
```

The robust penalties use a Charbonnier-style loss, so fast animation changes are not treated as hard violations. `clip_warm_start` controls initialization only: `previous` runs the established per-frame path to obtain a starting state, `frame0` copies the pilot pose, and `bind` starts from the bind/default pose. None of these warm starts replaces the global objective. `clip_contact_bones` currently defines contact stability as a velocity penalty on selected bones; it is deliberately explicit rather than pretending that a contact can be inferred without a target landmark.

Use `run_clip_pilot(experiment)` for a bounded notebook pilot, or enable the same setting before `run_full_animation(experiment)`. Start with a short `frame_indices` tuple and a small `pilot_bones`/`search_bones` selection before expanding the run; each proposal can require a Blender render.

### Motion-root translation

Whole-body travel is modeled as a separate parent above the imported armature, not as a translation of the camera or an arbitrary armature pixel offset. The solver keeps rotations on the skeleton and searches the root in model/world space using normalized body-length units. The worker reports the measured reference length and the forward/lateral/vertical basis in its `init` result, then applies the same root state to profile, reverse-profile, action-camera, preview, and proof renders.

The notebook controls are `motion_root_enabled`, `motion_root_axes`, the three `motion_root_*_radius_body_lengths` limits, and the coarse/refine body-length steps. The default pilot enables only bounded forward travel. `motion_root_magnitude_weight` discourages unnecessary displacement; the velocity, acceleration, and loop weights regularize clip motion without suppressing a legitimate fast step. `motion_root_coupled_blocks_enabled` adds the root to sparse dependency-local blocks so translation can be evaluated with major skeletal variables instead of only as an isolated afterthought.

The old `body_translation_*` fields remain accepted as configuration aliases. An explicit worker `bodyTranslationPx` request remains renderable for old callers, but the optimizer does not reinterpret the old `__body_translation_px__` pose key as body lengths because no camera pixel scale exists in the temporal objective. New searches emit `__motion_root__` with `forward`, `lateral`, and `vertical` values. Image-space camera alignment remains a fitting concern and is not delivered as animation motion.

`motion_root_loop_weight` and `motion_root_loop_velocity_weight` are root-specific seam penalties. They activate their corresponding root terms without requiring the generic `loop_enabled` switch; the generic loop switch still controls rotation-loop penalties.

### Bone order and ranges

The setup discovers the Blender hierarchy and derives dependency-aware order groups. Bone order can be:

- `dependency`: parent-to-child safe default;
- `reverse_dependency`;
- `alphabetical`;
- `explicit`, using `bone_order`;
- `branch_walk`, which walks hierarchy branches and can apply camera bias.

`search_bones` narrows the preferred list. `include_unlisted_search_bones` controls whether the remaining bones are appended or excluded.

`search_axes` chooses the Euler axes explored. `exclude_bone_roll=True` strips twist about the bone shaft after each delta, preventing X/Z changes from quietly introducing roll. `skip_tiny_bones` removes bones that are too small to be useful search controls.

### Single-bone coordinate descent

The default `multi_bone_mode="single"` searches one bone at a time. A coarse scan uses `coarse_step_deg`, followed by a refinement scan using `refine_step_deg`. `compound_cd_rounds` repeats passes so a later bone can respond to an earlier improvement.

`axis_probe_first` and `multi_axis_mode` control whether axes are probed independently or combined during candidate evaluation. `near_bone_refinement_enabled` adds a local pass over nearby hierarchy bones using `near_bone_refinement_step_deg`.

### Multi-bone search

The available modes are:

- `single`: established one-bone-at-a-time search;
- `block_coordinate`: optimize blocks of related bones over one or more rounds;
- `joint_beam`: keep several candidate pose states and expand them using a beam.

`multi_bone_grouping` is `window` or `branch`. `multi_bone_block_size`, `multi_bone_rounds`, `multi_bone_step_deg`, `multi_bone_candidate_pattern` (`star` or `cube`), and `multi_bone_beam_width` control cost and breadth. Larger values increase trials quickly and should be piloted on a small frame set first.

### Frame seeding

With `seed_from_previous=True`, the selected pose from one animation frame becomes the initial pose for the next frame. This improves continuity but can carry a bad local minimum forward. Set it false for independent-frame ablations.

`run_frame0_pilot` and `frame_indices` make it possible to test one frame or a small subset before attempting the full animation.

## IK Experiments

IK is optional and independent from the regular bone search.

`ik_enabled` must be true for any active IK mode. Modes are:

- `off`: no IK;
- `replace`: replace configured targets for the applicable pose path;
- `replace_all`: replace the full search path with IK-driven results;
- `add`: add IK to the normal pose path;
- `add_all`: apply IK across the full configured path.

`ik_bones`, `ik_chain_length`, `ik_iterations`, `ik_strength`, and `ik_depth` control the chain and solve behavior. Targets can be supplied directly through `ik_targets`, loaded automatically from `ik_target_source`, or searched in image space.

Target search uses:

- `ik_target_search_enabled`;
- `ik_target_search_only`;
- `ik_target_search_bones`;
- `ik_target_coarse_step_px`;
- `ik_target_refine_step_px`;
- `ik_target_search_radius_px`;
- `ik_target_min_improvement`.

The setup validates that target-search flags are not enabled without an active IK mode. `replace_all` can bypass normal rotation search, so its score can change without the ordinary bone optimizer selecting a different pose.

## Live Preview And Artifacts

With `live_preview=True`, the solver refreshes the RGB search composite at:

```text
<pilot_dir>/tmp/live_chroma_preview.png
```

The normal panel is target RGB, candidate RGB, and a depth/geometry diagnostic. `preview_every` controls how often the displayed image refreshes; it does not change the objective itself.

When anatomical preview is enabled, the second panel is written to:

```text
<pilot_dir>/roc_anatomical_boxes/live_feature_dots.png
```

It contains target and candidate images, colored feature dots, and a legend. Target overlays and metadata are written as:

```text
<pilot_dir>/roc_anatomical_boxes/sprite_<frame>_boxes.png
<pilot_dir>/roc_anatomical_boxes/sprite_<frame>_boxes.json
```

Candidate anatomical render and final-frame artifacts use the corresponding candidate/mesh names. The JSON records detector model, device, boxes, vocabulary, and the fact that this is local detector evidence rather than runtime proof.

`run_full_animation(experiment)` writes one rendered frame per configured index under:

```text
<pilot_dir>/<match_dir_name>/frame_<frame>.png
```

It also writes `report.json`, containing per-frame history, poses, score configuration, semantic configuration, anatomical configuration, IK target-search configuration, and the proof classification.

`run_semantic_report(experiment)` compares already rendered target/mesh pairs and writes a pairwise semantic report with cosine values and a mean cosine. This report is diagnostic and does not replace the full hybrid optimizer report.

## Suggested Experiment Order

Use small, attributable experiments rather than changing every control simultaneously:

1. Run one frame with geometry only.
2. Add semantic image scoring and compare the selected pose and score details.
3. Add one anatomical path and inspect target/candidate detections.
4. Test positive or negative text independently.
5. Compare single-bone coordinate descent with one multi-bone mode.
6. Add near-bone refinement only after the primary search is stable.
7. Add IK on a small frame subset and verify target provenance.
8. Enable frame seeding and inspect continuity across several frames.
9. Run the full animation and inspect every output class: RGB, anatomical overlays, pose history, and report metadata.

For ablations, change one weight or one mode at a time and use a distinct `match_dir_name`. Do not compare scores from runs with different active components without recording the component set.

## Common Failure Modes

### No anatomical dots or legend

Check the initialization output for `detected target box frames`, `scoring`, and `preview`. Anatomical detection requires CUDA. The preview file is `roc_anatomical_boxes/live_feature_dots.png`. Restart the notebook kernel after changing source fragments if the runtime still contains an older executed namespace.

### Detector reports a miss for a visible mesh part

The score currently treats detector failure and physical absence identically: the target part gets candidate distance `1.0`, score `0.0`. This is a detector limitation, not proof that the mesh lacks the part.

### Semantic model setup fails

Check CUDA, model availability, embedding-layer names, and whether text scoring requested the projected layer. The semantic lane intentionally fails rather than falling back to an unconfigured CPU or alternate model.

### Mesh appears melted or parts slide

The optimizer cannot repair ownership errors in the rig or skin. Verify the owned-bind gate separately. Do not use a low pixel error as evidence that the mesh deformation is correct.

### Full animation is too slow

Reduce `frame_indices`, use `run_frame0_pilot`, set `preview_every` higher, reduce multi-bone breadth, or disable multiview while testing. Do not silently disable an objective and then compare the result as though it were the same experiment.

### Reinitialization behaves inconsistently

Call `experiment.close()` or initialize through the public `initialize` function, which closes the active worker. Restart the kernel after editing source fragments if a partially executed cell left stale definitions behind.

## Related Pipeline Rules

This experiment belongs to the larger pose pipeline described in `.agents/skills/homm3-pose-pipeline/SKILL.md`. That pipeline requires authored sprite landmarks, an owned bind skeleton and skin, fixed-length rotate-only delivery IK, lit preview at the sprite timing, and skinned-mesh Olden Era delivery. A semantic hybrid fit can assist those steps, but it does not waive them.
