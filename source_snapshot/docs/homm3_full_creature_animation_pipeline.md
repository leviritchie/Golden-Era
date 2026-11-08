# HoMM3 Full-Creature Animation Pipeline

This is the current dataset-scale lane for turning Meshy smart-rigged
creatures into animated 3D clips. The notebook remains the interactive pilot;
the batch runner consumes the same `RocHybridConfig` values rather than
reimplementing the optimizer.

## Current execution contract

- Targets are the original VCMI/DEF frames. RIFE output is not an animation
  source and is rejected by the Crusader full-set runner.
- Shadow-culling remains part of target preparation. A target without the
  expected shadow-culled inventory is not silently substituted.
- The semantic encoder receives the RGB render, not a depth visualization.
  Depth and geometric scoring remain separate optional terms in the hybrid
  ledger.
- `roc_semantic_services.py` keeps bounded process-wide global and dense
  encoder instances alive across sequential clips. Target vectors are keyed
  by content digest plus model/preprocessing settings; dense target grids are
  stored on CPU and moved to the active CUDA device when reused.
- Depth Anything V2 Small is also kept in a process-wide pipeline cache. Its
  predicted maps are guarded by source-signature manifests, so repeated
  batches do not reload the depth model or recompute unchanged frames.
- The Blender-free geometric proxy is an optional triage lane, never part of
  the authoritative score. It is economically gated: waves with
  `n <= proxy_min_candidates` bypass it before target decode, GPU preparation,
  or any proxy evaluation. The default threshold is 8, so the first setting
  only pays for proxy work on waves of at least 9 candidates.
- Each proxy level computes its keep count before evaluating. A level is
  skipped when that keep count equals its input survivor count; in particular,
  Level 1 does not rerun the same four candidates after Level 0 has already
  reduced an eight-candidate wave to four.
- Rotation-vector exploration is protected by default through
  `proxy_protected_stages=("rotation_vector",)`. Its direction probes are
  fully scored because they establish the search coordinate system. The proxy
  remains available for larger beam, block, and root-hypothesis waves.
- When enabled, proxy shadow auditing renders a deterministic sample of
  rejected candidates through the full scorer. It records sampled
  `winner_recall`, `top4_recall`, proxy/full rank correlation, and
  `regret=max(rejected)-max(survived)`. Positive regret beyond the configured
  tolerance disables the proxy for that search class and reruns the remaining
  rejected candidates through the full pipeline for that wave.
- The proxy backend caches immutable GLB tensors per mesh/device, computes
  pose-dependent world transforms once per candidate wave, reuses that batch
  across Level 0 and Level 1, and rasterizes the projected points with GPU
  scatter rather than a Python loop. Bind-pose validation remains mandatory
  even when a candidate wave bypasses proxy triage.
- The full-set runner reuses the Blender worker pool across clips while the
  selected mesh is unchanged. The worker receives the same authoritative
  `init` contract with `reuseAsset=true`, resets clip-owned camera,
  compositor, and pose state, and keeps the imported GLB, armature, skin, and
  textures resident. A path or content-hash mismatch fails closed instead of
  fitting a different mesh.
- `--fit-only` fits and stores sparse original-frame poses without
  interpolation, 60 fps review rendering, GIF creation, MP4 creation, or a
  process-wide review-frame list. This is the production fitting pass.
- Review rendering is a separate operation. The existing default runner mode
  still produces per-clip and aggregate 60 fps reviews for pilot-sized runs;
  it should not be used as the first pass over hundreds of clips.
- `run_clip_pilot(experiment)` owns one `tqdm.auto` progress bar across both
  the warm-start frames and the global clip search. It reports completed unique
  renderer/encoder evaluations, plus the current search stage and score. The
  total is intentionally open-ended because cache hits, batching, proxy
  triage, and adaptive proposals change the final count. `progress=False`
  remains available for headless callers.

## Recommended sequence

1. Use the notebook picker to verify the selected unit, animation, mesh path,
   camera fit, and frame-00 preview.
2. Run the full-set command with `--fit-only` and a bounded `--limit` first.
   Resume is manifest-based and checks the notebook hash, mesh identity, and
   sparse pose artifact.
3. Inspect the sparse pose manifests and timing summaries. Only send failed
   or representative clips through the review renderer.
4. Assemble GIF/MP4 review output after fitting, rather than retaining every
   interpolated comparison frame during the fitting run.

For the current Crusader lane:

```powershell
py -3 tools/homm3_silhouette_pose_fit/run_crusader_full_animation_set.py `
  --fit-only `
  --out V:/Games/Olden Era Playtest Tweak/artifacts/crusader_semantic_full_set_smartrig
```

Use `--no-persistent-blender-workers` only when isolating worker lifecycle
behavior or diagnosing scene contamination. The default reuses the worker
pool for sequential clips.

The reusable picker-driven entry point is:

```powershell
py -3 tools/homm3_silhouette_pose_fit/run_creature_animation_set.py `
  --unit all `
  --fit-only `
  --out V:/Games/Olden Era Playtest Tweak/artifacts/full_creature_animation_set
```

It discovers every unit/animation choice currently exposed by the picker and
resolves the matching `<unit>_smartrigged.glb` from
`artifacts/meshy_downloads` by default. A post-rigidization derivative still
requires its passing adjacent report; a direct Meshy smart-rig is recorded as
such. If no deterministic Meshy filename exists, the runner uses the choice's
authoritative pipeline mesh as a fallback. Use `--use-picker-mesh` to force
that per-choice mesh, or `--allow-unverified-mesh` for an explicitly
diagnostic arbitrary mesh. Use `--dry-run` to inspect the inventory and
resolved mesh paths before starting Blender.

## Cache controls

The notebook config exposes the semantic service controls:

- `semantic_service_enabled`
- `semantic_service_cache_generation` (bump after encoder/checkpoint code changes)
- `semantic_service_encoder_cache_max_entries`
- `semantic_service_target_cache_max_entries`
- `semantic_service_dense_target_cache_max_entries`

The defaults retain the global and dense encoder needed by the current
SigLIP2/DINO-style configuration while bounding model and target memory. The
service reports hit/miss counts through `experiment.summary()` and
`performance_snapshot()`.

The proxy controls are also exposed directly in `RocHybridConfig`:

- `proxy_min_candidates`
- `proxy_protected_stages`
- `proxy_audit_enabled`
- `proxy_audit_fraction`
- `proxy_audit_max_candidates`
- `proxy_audit_regret_tolerance`
- `proxy_gpu_tensor_cache_enabled`
- `proxy_gpu_asset_cache_max_entries`

`performance_snapshot()` includes proxy bypass/skip counts, audit history,
invalid search classes, and the full-fallback count. Treat audit recall as
sampled recall unless every rejected candidate in a wave is shadow-scored.

## Proof boundary

The semantic service, fit-only runners, picker discovery, and worker-pool
resident-asset path are source-validated and covered by focused Python smoke
tests. The resident-asset branch still needs a focused Blender invocation
before it can be called runtime-proven. A complete hundreds-of-creatures run,
its elapsed-time target, and its user-visible quality are also not proven by
These source checks. A persistent on-disk target-feature manifest, family
priors, and distributed queue remain follow-up work.

## Deliberate motion, loops, and transitions

Skinned delivery now has one lifecycle contract (`deliberate_motion_contract.py`).
Cycle clips export `N` source poses plus a sign-aligned copy of frame 0 at
`N * frameDuration`. Delivery duration is owned by authentic DEF playback
(1/12 s per pose), not solver FPS and not the 180 ms preview GIF clock.
`loopTime` comes from `lifecycleRole`. After a cycle clip exists, velocity and
acceleration must score the loop seam in both time directions (last↔first and
first↔last). That wrap is off during the initial `CURRENT_CASCADE_KEEP` fit
(`temporal_loop_wrap_enabled=false`) and is applied afterward by
`circular_temporal_score.py` / `apply_circular_temporal_after_setup.py`.
Physics smoothing remains a pilot polish pass; it is not readiness. Gate:
`tools/validate_deliberate_motion_contract.py`.
Plan: `docs/homm3_deliberate_motion_loop_transition_plan.md`. Stronghold
inventory: `artifacts/deliberate_motion_baseline.json` (generated-artifact
only; full-animation readiness is blocked on one-pose MoveStart/MoveEnd,
missing landmarks, and the stock Idle↔Move bypass).
