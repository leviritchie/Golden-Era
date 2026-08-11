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

The current notebook experiment uses `google/siglip2-base-patch16-512` with
batch size `1` for both the optimizer and report cell. The semantic transfer method is proven; this
particular encoder replacement is an active benchmark and must not yet be
treated as equivalent to the previous CLIP baseline without comparing pose
convergence and final-frame quality.

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

## Notebook

The experiment is maintained in:

`tools/homm3_silhouette_pose_fit/roc_chromatic_single_bone_match.ipynb`

The semantic-only toggle is `SEMANTIC_ONLY = True`. It disables depth and
silhouette as decision scores while retaining the RGB live preview and the
original-frame-only target contract.

## Adaptive optimizer pilot

The notebook also contains the semantic optimizer pilot, enabled by
`SEMANTIC_OPTIMIZER = True`. It performs bounded coordinate descent one bone and
axis at a time:

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
