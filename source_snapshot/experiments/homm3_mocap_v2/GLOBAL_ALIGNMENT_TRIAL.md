# Shared Image-Scored Alignment

2026-09-07. Generated diagnostic only; no production selection, preparation,
camera, source capture, skin weight, or mesh geometry changed. Not promoted.

`run_global_motion_alignment.py` builds the explicit source-reference bind,
then freezes its deformation palettes. `global_motion_alignment.py` fits one
shared correction B across every clip by B D B^-1. Rotation mode has three
parameters; similarity mode has seven. Rotation uses a matrix exponential;
scale is bounded to .5..2 and translation delta to +/- .25 mesh span around
the mesh center. Neutral D=I remains identity. No per-frame or per-bone fit.

V2 evaluates 24 proper cube orientations. Similarity mode evaluates those
orientations at relative scales 1, .625, 1.6. The three best training-scored
configurations each receive 180 gradient steps; best checkpoint selection is
training-only. These are fixed generic seeds, not unit-specific angle fixes.
Camera, source-reference skin and texture remain identical for each search.
The prepared control has its original prepared skin; it is a separate baseline,
not an assertion of identical skin between preparation methods.

Each unit includes all 15 groups / 92 frames. One interior frame of each clip
with at least five frames is withheld: 83 training and 9 withheld frames per
unit. Reports retain explicit frame IDs, per-frame scores, split loss metrics,
coarse scores, selected seed/step, correction matrices, palette/skin hashes,
surface/depth metrics and input/implementation provenance. Holdouts are nearby
frames from known clips, not unseen units or unseen animation types.

## Results

V2: `artifacts/homm3_mocap_v2/skin_mesh_pilot/{thunderbird,shahrokh}/global_alignment_v2/`.
Both implementation ledgers were verified against current source after runs.
All numbers below are mean silhouette IoU; higher is better.

| Unit / method | All frames | Training | Withheld |
| --- | ---: | ---: | ---: |
| Thunderbird prepared | .548298 | .556413 | .473462 |
| Thunderbird source-reference | .456914 | .460654 | .422419 |
| Thunderbird shared rotation | .490510 | .498101 | .420507 |
| Thunderbird shared similarity | .568370 | .576964 | .489121 |
| Shahrokh prepared | .534410 | .544981 | .436913 |
| Shahrokh source-reference | .489407 | .490756 | .476963 |
| Shahrokh shared rotation | .518325 | .528746 | .422222 |
| Shahrokh shared similarity | .563984 | .577879 | .435840 |

Shared similarity improves aggregate scores, but Shahrokh's withheld result
is below prepared and substantially below its source-reference baseline.
Both fits select near-lower-bound relative scale (.512099 and .504105), not a
clean rotation correction. Depth clipping remains (3637 and 8837 vertex-frame
samples). Inspected move contact sheets still have wrong-looking wingbeats.
Therefore this trial does not satisfy the animation objective and is not
promoted. Do not present aggregate overlap as proof of deliberate wing motion.

Cached search/render/score elapsed 39.11 and 41.40 seconds, total 80.51 seconds.
No new mocap, weight/mesh optimization, GLB export or runtime proof in this lane.
Earlier Thunderbird V1 was single-start, took 25.50 seconds, and lacks V2's
explicit split summary and multistart search. It is not a current-code rerun.
Engineering, CPU tests, review and investigation are additional time.

## Verification And Next Boundary

77 focused tests pass across alignment, bind, motion, skin/mesh and serialized
replay. New checks cover 24 determinant-positive seeds, positive scale seeds,
analytical translation rotation/scaling, rigid per-bone transforms under
similarity conjugation, finite gradients at identity, one 3/7-parameter module,
and detached unchanged source data. Independent Luna review found no remaining
leakage or fallback. All source-reference palettes and input files are checked
unchanged after each run. These tests do not validate visual quality.

Global alignment alone has not resolved the wingbeat. Check source-frame
correspondence and spatial skin ownership with discriminating evidence before
another corrective algorithm. In particular, do not silently shift, reverse or
retime the capture to make previews look better. All 21 Stronghold units remain
scope and none is promoted by this diagnostic.

Follow-up read-only timing audit found no pipeline phase shift on Thunderbird
move: 12 context frames, authored indices 12..17, 12 trailing context frames;
30 numbered PNGs, 30 embeddings and 30 predicted poses. Numerical input order
and output indexing are retained without downsampling/reversal. This rules out
an explicit indexing offset, not semantic prediction errors. A wing-tip angle
between both spine-to-tip vectors is smallest on authored frame 3, but that
angle alone cannot distinguish wings rising together from an incorrectly closed
wingbeat. Do not use it as independent 2D ground truth or justify retiming.
