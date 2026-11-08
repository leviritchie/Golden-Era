# Behemoth and Hobgoblin Full-DEF Trial

Generated diagnostic candidates, 2026-09-06. Nothing installed or deployed.
Neither unit passes the final animation-quality gate. This is not a repeat of
the Roc visual result and must not be described as accepted animation delivery.

## Inputs and Method

- Behemoth: 85 authentic DEF frames, 15 groups; original pinned
  `artifacts/meshy_downloads/h3_behemoth_smartrigged.glb`.
- Hobgoblin: 88 authentic DEF frames, 15 groups; original pinned
  `artifacts/meshy_downloads/h3_hobgoblin_smartrigged_rigidized.glb`.
- Both use the unmodified installed 25-joint Mixamo capture package recorded in
  `capture_candidates.json`. No independent finger/claw articulation is inferred.
- Every group retains its authored frames and 12 FPS timing. Idle context is
  excluded from target/export frames. Movement uses authored start/cycle/stop
  context; death has no invented recovery.
- One asset-wide captured idle reference and one original-idle camera are frozen
  before optimization. Joint trajectories are not trained by the image scorer.
- The same repair, skin, shared-rest-mesh, and final all-frame optimization stages
  used by the Roc trial are run with the same iteration settings.

Preparation required an explicit change of initialization. The human surface
proxy rejected 1,061 Behemoth correspondences. Its thresholds were not loosened.
`prepare_mapped_skin_asset.py` instead initializes both units from their existing
skin weights using a complete explicit source-joint-to-donor map. It sums mapped
weights, restricts them to anatomical support, and renormalizes. Zero support is
an error, not a nearest-bone fallback. This is an initializer, not the final skin.

Actual GLB joint coordinates and hierarchy supersede old anatomy labels. The old
Behemoth quadruped labels were wrong; Hobgoblin labels referred to different bone
numbering. Both current profiles cover every source bone explicitly. Positive-X
target limbs map to the donor's Left limbs. Hobgoblin Bone_023 owns the 577 mace
vertices, held at exact RightHand weight with zero mesh-field displacement.

## Results

| Measurement | Behemoth | Hobgoblin |
| --- | ---: | ---: |
| Fresh all-group capture, including encoding | 141.14 s | 163.62 s |
| Shared fit, GIFs, export checks | 199.08 s | 92.45 s |
| Capture plus fit | 340.22 s | 256.08 s |
| Successful mapped preparation | 57.97 s | 49.88 s |
| Idle registration | 16.27 s | 2.89 s |
| Rest geometry gate | Pass | Pass |
| Idle appearance gate | Fail | Pass |
| Animated surface gate | Fail | Fail |
| Depth clipping gate | Pass | Pass |

Times exclude investigation, failed preparation attempts, and later test runs.
They are measured all-group run times, not a claim that a new unit is ready in
that time without preparation. All 30 exported candidate clips passed serialized
animation parity; parity does not imply acceptable appearance.

Behemoth idle alpha MAE is 0.006658, exceeding the existing 0.005 threshold.
Hobgoblin is 0.001309. Behemoth's raised-arm attack and viewing presentation do
not match the source well. Hobgoblin's mace stays rigid, but the attack reach is
understated. Skin/mesh optimization does not repair these motion mismatches.
Do not increase deformation freedom merely to hide them.

## Artifacts

All paths below are relative to the repository root.

- Behemoth source corpus: `artifacts/homm3_mocap_v2/skin_mesh_pilot/behemoth/corpus_v2/manifest.json`.
- Hobgoblin source corpus: `artifacts/homm3_mocap_v2/skin_mesh_pilot/hobgoblin/corpus_v1/manifest.json`.
- Each unit's `captures_v1/corpus.json` pins every source image and raw capture.
- Each unit's `registration_v1/` pins the camera and common idle calibration.
- Each unit's `all_def_v1/` contains `report.json`, `diagnostic_candidate.npz`,
  and all 15 `{group}_comparison.gif`, contact PNGs, and candidate GLBs.
- Common GIF columns: Source, Original (initial mapped skin under mocap),
  Constrained skin, Skin + mesh. Original does not mean original HoMM3 3D motion.
- Prepared assets live under `artifacts/homm3_mocap_v2/shape_preserved/{asset}/preparation/mapped_skin_v1/`.
- Hobgoblin's earlier proxy preparation was superseded before fitting. Its freeze
  was retained as `preparation_proxy_superseded.json`; it is not the active input.
- Behemoth `corpus_v1` is an incomplete failed attempt at comparing historical
  shadow-bearing idle plates. `corpus_v2` normalizes DEF shadows on both sides.

## Validated Contracts

Preparation/export enforce complete anatomical coverage, complete explicit
source-joint mapping, normalized bounded anatomical support, exact rigid prop
weights, unchanged original rest surface, and GLB reload parity. Mapped skin
readback requires the profile fingerprint and research-skin SHA to match.
Existing mapped-v1 files were independently recomputed and checked against the
current fit, weights, skeleton, inverse bind, vertices, topology, UVs, albedo, and
regions before provenance pins were added; no binary artifacts were rewritten.

Validation: 25 focused CPU tests passed, and 28 CUDA-enabled skin tests passed.
The suites overlap in the seven mesh-pilot tests. A Windows TemporaryDirectory
ACL failure was corrected in the fixture setup using a unique workspace folder;
the substantive normalization test subsequently passed against the real shadow
culler. These are research pipeline gates, not a Golden Era runtime validation.
