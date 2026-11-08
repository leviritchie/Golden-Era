# Original T2 Full-Animation Repair

2026-09-12. User-requested comparison on the original T2 Ogre Mage and combined
Boar Rider, without neutral-pose generation or a newly authored bind. Generated
diagnostics only; neither candidate is visually accepted, exported, or deployed.

## Coverage And Controls

| Unit | Authentic source groups | Source frames | Existing pilot poses preserved exactly |
| --- | --- | --- | --- |
| Ogre Mage | 18 | 109 | 24 |
| Boar Rider | 15 | 83 | 29 |

Every available group is included, including turns, directional attacks, extra
groups, and native transition frames. The normal native-delivery reel selector
excludes some of these groups, so this diagnostic uses an explicit corpus list
instead. Full source coverage is not a claim that every group is used in-game.

The original T2 mesh, saved bind, fitted baseline weights, and camera remain the
inputs. No T-pose, new rest landmarks, new mesh, or actor split was introduced.
The Boar's previously authored mounted rest and seated policy are retained, not
claimed to have become autonomous or anatomically correct.

Existing pilot clips retain byte-identical joint-world transforms. Additional
Ogre clips use a 100-frame capture episode; additional Boar clips use a 64-frame
episode captured for each actor. Context frames are excluded from displayed
source coverage. New motion uses each original canonical capture reference and
the existing bind, rather than a newly predicted episode-zero bind. Death is
terminal in each remainder episode, without a fabricated recovery frame.
Cross-episode transition continuity remains unproven.

## Repair Result

The same shared repair-only optimizer runs 150 iterations over all source poses
for each unit. Geometry, UVs, textures, skeleton, camera, and motion are fixed;
only skin weights change. Support is restricted to the baseline's existing
influences. Existing incorrect influences can remain; support containment is
not anatomical correctness. No image-fit, motion-floor, or rest-mesh stage runs.

| Entire corpus metric | Ogre before | Ogre after | Boar before | Boar after |
| --- | --- | --- | --- | --- |
| Maximum triangle principal stretch | 16.543 | 9.409 | 28.113 | 11.885 |
| Minimum triangle principal stretch | 0.00496 | 0.05392 | 0.00166 | 0.02306 |

Each clip's maximum stretch decreased, but severe localized distortion remains.
Ogre Attack Up still reaches 9.41x and Defence 6.22x. Boar Death reaches 11.89x,
Attack Up 10.85x, Hit 9.58x, and Attack Front 8.49x.

Repair does not freeze the units, but some surface trajectories change materially.
Ogre right-leg peak excursion retains approximately 89% in Attack Front and Hit;
its turning right-arm trajectory-relative error is approximately 28%. Boar retains
at least approximately 94% peak excursion among the meaningfully moving regions
inspected, while torso trajectory error reaches approximately 37% in Defence.
Region membership is inherited from the initializer, not anatomical ground truth.

The Ogre still misses the source staff action and shows broad surface deformation.
The Boar still has facing, attack, and death-pose errors. A weight-only repair
cannot be credited with correcting the underlying source-motion mismatch.
Neither output passes visual acceptance.

Measured optimizer times are 9.79 seconds (Ogre) and 9.84 seconds (Boar), excluding
capture, setup, rendering, and review. These are not fleet-throughput estimates.

## Review Artifacts

Root: `artifacts/homm3_mocap_v2/stronghold_full_repair_v1/`.

- `index.html`: offline unit/clip selector, all 33 individual groups plus reels.
- `ogre_mage/repair/` and `boar_rider/repair/`: source / saved baseline / repair
  GIFs, reports, candidate weights, and independent per-clip audits.
- One all-frame union crop is applied equally to all three panels and clips.
  Original projection/canvas is unchanged; there is no per-frame reframing.
- Native 12 fps timing is retained using GIF centisecond rounding. Reels are
  clip comparisons, not a claim of seamless continuous choreography.
- Ogre bundle is under `ogre_mage/`; Boar bundle and capture provenance are under
  `../stronghold_full_motion_v1/boar_rider/`.

## Verification And Scope

Input hashes, rigid world matrices, complete clip partitioning, source canvas
bounds, baseline playback parity, reference rest identity, weight normalization,
and support containment were checked. Independent CPU readback verified original
pilot-pose equality and audited every clip rather than relying on pooled results.
Three Boar producer tests pass. Headless browser checks passed both unit selectors,
all clip option counts, image loading, and desktop/mobile layout without overflow.

This work restores an existing repair capability to a controlled diagnostic on
the simpler original-T2 path. It does not integrate a new production pipeline,
modify shared runtime code, or establish that either unit is ready to ship.
Keep these direct-T2 results as the comparison before considering further mesh
generation; source motion and residual binding faults remain explicit.
