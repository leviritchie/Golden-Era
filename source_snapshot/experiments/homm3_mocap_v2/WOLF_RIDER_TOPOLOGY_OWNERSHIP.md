# Wolf Rider topology-aware ownership trial

Status: generated diagnostic candidates, not promoted. No runtime delivery,
new mocap inference, pose optimization, or central frozen-preparation changes.

Identity correction: the target in this historical trial is the Wolf Raider
mesh, despite its Wolf Rider filename. The source DEF was Wolf Rider. See
`WOLF_RIDER_IDENTITY_CORRECTION.md`; these candidates must not be promoted as
correctly paired unit assets. The measured weight-continuity experiment remains
diagnostic evidence on those exact bytes, not a corrected-unit quality result.

## Question and method

Can surface-continuous weights reduce the deformation produced by hard regional
ownership without simply suppressing movement?

The source skin has 12,863 vertices and 15,122 triangles. Exact-coordinate
welding produces 7,531 positions, 22,734 edges, and one connected component.
This is not a collection of disconnected rider/mount shells. Triangles at
regional ownership boundaries can therefore receive conflicting movements.
Connectedness does not, by itself, locate an anatomically incorrect bridge.

`topology_owned_skin.py` solves a screened harmonic weight field on existing
surface edges. It preserves geometry, triangle indices, UVs, texture, skeleton,
bind matrices, and source region labels. Coincident vertices share weights;
20 welded weapon positions retain their original rigid owner. Original region
labels provide the prior, not hard support barriers. This is weight continuity
correction, not actor separation or mesh surgery.

The solve explicitly projects to eight influences per vertex and reports the
removed mass. Candidates are incompatible with the previous hard regional
support contract and must not replace the frozen preparation automatically.

## Controlled results

Artifacts: `artifacts/homm3_mocap_v2/skin_mesh_pilot/wolf_rider/`.
Each `topology_owned_vN` folder contains preparation and validation reports.
All candidates use identical geometry and the same original weights as prior.

| Candidate | Prior strength | Preparation seconds | Triangle-pose violations | Minimum motion retained | Strict quality |
| --- | ---: | ---: | ---: | ---: | --- |
| Original | - | - | 3188 | 100% | Fail |
| v1 | .05 | .629 | 681 | 86.0% | Fail |
| v2 | .015 | .568 | 281 | 73.0% | Fail |
| v3 | .005 | .564 | 182 | 56.8% | Fail |

Counts aggregate 36 independent probes: both rider arms and mount neck, each
rotated about three world axes at +/-30 and +/-60 degrees. A violation is a
triangle with mean edge-length ratio outside .5..2, including compression.
These are triangle-pose counts, not counts of unique bad triangles, and this
metric is not a principal-strain or self-intersection guarantee.

The 70% motion-retention gate prevents a smoother but excessively subdued result
from winning. v2 reduces violations by 91.2% and passes that gate; it still fails
the absolute surface gate. v3 is rejected for losing too much movement. v2's
eight-influence projection removes 7.1% weight mass on average and up to 35.1%
at a vertex. This is a material limitation, not an invisible export operation.

## Visual proof and limits

`topology_owned_v2/frozen_motion_preview/` compares source DEF frames, original
skin, and candidate using the exact previous composed FK motion. The comparison
manifest pins source, candidate, corpus, and per-clip motion hashes. Move, idle,
and front attack were rendered; no new capture or fitting occurred. These are
raw fixed-motion diagnostics, not comparisons against a newly optimized result.

Attack and move contact sheets were inspected. The visible difference is modest
in these trajectories despite the larger actuator-probe improvement. The rider
still does not perform the source's forward strike. Weight continuity cannot
repair missing joint motion. No final animation quality pass is claimed.

Validation: 61 focused and regression tests passed on the mocap venv. A Luna
review agent inspected the solver and probe comparison; no additional critical
reproducible defect was reported. All three candidate reports were regenerated
with the final validator. CPU solver and invariant tests exercise actual sparse solving, coincident
vertices, rigid pins, normalized bounded influences, and invalid inputs. The
candidate validator is a research gate, not a build/deploy integration: there
is deliberately no candidate delivery route in this change. Any future route
must invoke the ownership and surface gates rather than bypassing them.

## Next decision

Do not spend another capture/fit cycle assuming skin smoothing solved the
mounted-unit problem. Retain this solver as a measured candidate preparation
option. Next isolate the rider's missing torso/arm strike with source-supported
motion constraints while keeping mount motion fixed. Require visible strike
agreement and actor-contact checks before joint skin/mesh fitting. Remaining
surface failures need localized diagnosis; stronger global smoothing has already
demonstrated unacceptable motion loss.
