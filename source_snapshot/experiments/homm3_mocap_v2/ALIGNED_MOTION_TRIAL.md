# Source-Frame Alignment Trial

2026-09-06. Rejected for promotion on the expansion cohort. Existing pipeline
defaults, captures, preparation skins, fitted skins, cameras, and exports are
unchanged. Generated diagnostic evidence only; no delivery or runtime proof.

## Controlled Comparison

`aligned_capture_motion.py` explicitly normalizes the source reference, capture
positions, and offsets into the fitted bind frame before invoking the existing
retargeter. The target is unchanged. This removes the articulated source-gauge
sensitivity demonstrated by `diagnose_retarget_source_frame.py`; it does not
establish correct image-space motion or correct camera facing.

`compare_aligned_capture_motion.py` compares this candidate against `load_motion`
with identical original geometry, continuous-fit skin weights, registration,
calibration, capture indices, and authentic source frames. It does not fit or
export a new delivery asset. All groups are included. Mounted composed FK is
explicitly unsupported, not silently rerouted. Output directories cannot be
overwritten. Input hashes are checked and recorded in each report.

Results live under `artifacts/homm3_mocap_v2/skin_mesh_pilot/<unit>/aligned_motion_v1`.
Each contains report.json, per-clip motion NPZs, GIFs and contact sheets. GIF
columns are source, current motion, source-frame aligned motion. Goblin uses
mapped_skin_v2 and continuous_fit_v1, without its separate leaf-weapon correction.

## Results

Frame-weighted means over all frames, not averages of clip means. Higher IoU is
better; color is absolute RGB error and LOWER is better.

| Unit | Groups / frames | IoU current -> aligned | Color error current -> aligned | Comparison seconds |
| --- | --- | --- | --- | --- |
| Orc | 18 / 103 | 0.534075 -> 0.527739 | 0.452973 -> 0.456029 | 18.963 |
| Ogre | 15 / 85 | 0.580190 -> 0.557434 | 0.417509 -> 0.419994 | 14.933 |
| Cyclops | 18 / 125 | 0.555282 -> 0.543889 | 0.700882 -> 0.704603 | 21.481 |
| Goblin | 15 / 88 | 0.634876 -> 0.636491 | 0.327765 -> 0.329357 | 15.619 |

66 groups / 401 frames tested. Silhouette agreement declines for every new unit;
Goblin improves only marginally. Color error worsens for all four. Fixed bone
lengths remain numerically preserved (worst error 5.17e-15), but this is not a
surface-quality gate. Worst recorded surface stretch also worsens for Orc
(4.148 -> 4.173), Ogre (9.812 -> 11.051), and Cyclops (8.936 -> 9.078).

Contact-sheet inspection confirms no resolution of Orc's understated throw,
Ogre's direction mismatch, Cyclops' rear-facing presentation and attached rock,
or Goblin's attack reach. No unit is newly accepted from this comparison.

The 71.0 seconds total above measures cached comparison, rendering and reporting
only. It excludes source preparation, capture, skin fitting, startup overhead,
agent investigation, review and orchestration. It is not end-to-end production
time and does not establish the under-ten-minute-per-clip delivery target.

## Validation and Decision

Repository-venv unittest discovery with pattern `test_*aligned_capture_motion.py`
passes 8 tests. Numerical tests cover articulated gauge invariance, nonidentity
motion, root travel, proper rotations, bind identity, fixed lengths and immutable
inputs. Runner tests exercise provenance/preflight failures, not CUDA. All four
actual comparison runs completed with exit code zero and provide GPU evidence.

Do not enable this candidate as a pipeline default or add unit-specific angles
to rescue it. Keep it as a reproducible rejected experiment. Continue breadth
testing with Orc Chieftain, Ogre Mage and Cyclops King using their own verified
asset identities and anatomy mappings, not copied sibling bone indices. The
expansion protocol remains authoritative: identify shared failures across units
before another solver change, and preserve the stronger prior results.
