# Roc Semantic Sprite-to-Mesh Transfer

## Status

**Proven primary path.** The semantic image-embedding comparison is the current
authoritative method for transferring the Roc's original 2D animation frames to
the Meshy smart-rigged mesh. It supersedes the earlier sprite-to-mesh attempts
based on hand-placed joints, skeleton overlays, bounding-box alignment, depth
IoU, silhouette IoU, chromatic silhouette matching, and RIFE-frame fitting.

The earlier methods remain available as diagnostics and research controls, but
they are not competing delivery paths and must not be treated as the default
solver when semantic comparison is enabled.

The current notebook experiment uses `google/siglip2-base-patch16-512`. Its
performance profile exposes separate global-image and dense-feature batch sizes
(`semantic_global_batch_size=16` and `semantic_dense_batch_size=8` by default);
these are independent CUDA-memory controls and should be reduced separately if
one encoder exceeds the available VRAM. The semantic transfer method is proven;
this particular encoder replacement is still an active benchmark and must not
yet be treated as equivalent to the previous CLIP baseline without comparing
pose convergence and final-frame quality.

The reusable runner is required to reproduce the notebook's active compound
search settings: `768x683`, `searchScale=0.35`, and the notebook's batched
multi-bone stages. Before the legacy Euler proposals, the active pilot now
searches an eight-direction rest-space rotation-vector shell at `16` degrees,
continues the two strongest directions at `32`, `64`, and `128` degrees when
enabled, and records when a bone is range-limited. The adaptive twist policy
keeps ordinary swing proposals roll-free while adding explicit scored twist
proposals; `bone_twist_overrides` can force `include` or `exclude` for a named
bone without changing the scalable default. The default runner embeds the
complete camera canvas and carries the previous committed pose into the next
frame; subject-crop embedding and no-seed execution are explicit diagnostics.

## Proven comparison

For each candidate bone pose:

1. The notebook loads the original, shadow-culled sprite frame.
2. Blender renders the posed mesh from the fixed sideways-profile camera.
3. The worker writes a true RGBA RGB render for the encoder. It does not pass the
   depth-packed compositor buffer to the encoder.
4. The same GPU vision encoder embeds the target sprite and candidate mesh
   render.
5. The candidate score is cosine similarity between the normalized embeddings.
6. The winning pose is preserved before testing the next bone, so later bones
   optimize against the accumulated motion rather than restarting from bind.

The depth compositor may still run for diagnostic scoring, but semantic requests
explicitly use the RGB render path. Live previews therefore show the actual
sprite and textured mesh render seen by the encoder, not a depth visualization.

## Performance finding

Semantic comparison was tested in the first-frame pilot and is not meaningfully
slower than the previous scoring paths in this setup. Blender render and file
handoff time dominate the loop; encoder embedding is not the limiting stage.
The implementation therefore favors semantically useful candidate evaluations
over premature embedding approximation or CPU-side shortcuts.

The current performance pilot keeps the objective exact while reducing repeated
work in this order:

1. Blender returns the cheap worker geometry/silhouette terms.
2. Conservative silhouette triage retains a bounded candidate set for semantic
   encoding. This is a heuristic ranking gate, so rejected candidates are not
   stored in the exact result cache.
3. A mathematical branch-and-bound upper bound treats every still-unknown
   normalized semantic/text term as `1.0`. With zero margin, it can reject only
   a candidate that cannot beat the current incumbent under the active weights.
4. Global SigLIP image embeddings run before dense feature matching.
5. Candidate pose/result values, target vectors, global candidate vectors, and
   dense scores are memoized within the initialized experiment. Cache keys carry
   the effective render/scoring contract; fully scored candidates are cached,
   while heuristic triage and bound rejections are not.
6. Clip polish is restricted to accepted or objectively sensitive axes, with
   optional dependency-group neighbors. Sensitivity is measured from the
   coarse proposal span, and the final committed poses are still rescored with
   the complete objective.

`performance_snapshot()` reports cache hits/misses, branch-bound prunes,
semantic survivor counts, and worker-batch time. These are instrumentation
signals rather than a claim that a particular triage fraction or worker count
is globally optimal; worker count and the two encoder batch sizes remain
hardware-dependent tuning parameters.

## Notebook

The experiment is maintained in:

`tools/homm3_silhouette_pose_fit/roc_chromatic_single_bone_match.ipynb`

The semantic-only toggle is `SEMANTIC_ONLY = True`. It disables depth and
silhouette as decision scores while retaining the RGB live preview and the
original-frame-only target contract.

Both the notebook compound path and the reusable runner apply semantic cosine
to every compound candidate; the worker's IoU is retained only as a
diagnostic field. The earlier notebook compound function accidentally left
the worker depth score authoritative even while the semantic toggle was
enabled, so an apparently semantic notebook run and the standalone runner
were solving different objectives.

The vector stage is also used by the global clip optimizer. Its acceptance is
still based on the complete clip objective, so a locally weak first probe can
be retained as a continuation direction without being committed unless a
larger-radius candidate improves the global objective. Quaternion pose entries
carry their twist policy through the worker; they are not converted back to
assumed global Euler axes until a later legacy coordinate pass explicitly asks
for that representation.

## Adaptive optimizer pilot

The notebook also contains an experimental semantic optimizer pilot, but it is
currently disabled by default (`SEMANTIC_OPTIMIZER = False`) because it did not
match the established coarse/fine solver reliably. The active solver is again
the previous coarse/fine search. When explicitly enabled, the experimental
optimizer performs bounded coordinate descent one bone and axis at a time:

- evaluate the current angle and both signed directions;
- keep a move only when semantic similarity improves by the configured margin;
- halve the angular step when neither direction improves;
- stop at the minimum step or per-axis evaluation budget;
- preserve the selected pose before continuing to the next axis and bone.

This is an experiment to reduce the number of Blender evaluations, not a claim
that the optimizer has already beaten the prior exhaustive search on every
frame. Its score history and per-evaluation timings are recorded in the
notebook output so the pilot can compare convergence and final semantic score
against the existing coarse/refine solver.

## Reproduction contract

- Use original animation frames only; do not substitute RIFE interpolations.
- Use the shadow-culled RGBA targets.
- Keep the model in the fixed sideways-profile camera.
- Require CUDA for the vision encoder.
- Keep `previewRgb=True` on live requests so previews and encoder inputs are the
  same image domain.
- Treat the semantic cosine score as the pose-selection score.
