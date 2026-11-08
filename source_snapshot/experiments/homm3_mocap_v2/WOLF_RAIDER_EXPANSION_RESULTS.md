# Wolf Raider Expansion

2026-09-06. Generated candidate only; rejected quality gates. No production
motion changes, delivery, or replacement of previously preferred results.

## Preparation And Motion

Semantic h3_wolf_raider uses the 57-joint b15de4 mesh now named
h3_wolf_raider_smartrigged.glb (legacy name h3_wolf_rider_smartrigged.glb until the 2026-09-27 swap). mounted_asset_identity.py owns that pin.
wolf_raider_anatomy.py partitions every named source bone. The source rig has
no independent rider torso/head chain; its head is largely owned by arm weights.
Torso/head anchors and bounded ownership volumes are explicitly estimated,
not inferred mocap landmarks or accepted anatomy. Four-view named source-region
and ownership-probe sheets were inspected before fitting.

The existing mounted authoring builder now selects Rider or Raider explicitly,
with Rider still the default. Missing source inventories, duplicates, unknown
anchors/regions, invalid volume bounds and ambiguous rigid owners fail closed.
These checks run during asset authoring/preparation, not as a runtime patch.
The sword remains rigidly owned by the selected profile's right-hand attachment.

The owned composite contains 61 joints: Coyote mount plus seated Mixamo rider.
Both actor captures come from Raider's own CUWLFR source plates. Composition
uses the existing fixed FK policy, including held seated rider legs. Source
indices retain all 15 groups / 80 authored frames and existing context frames.
No per-clip pose adjustments or new retarget method were introduced.

## Results

Outputs under artifacts/homm3_mocap_v2/skin_mesh_pilot/wolf_raider:

- authoring_v1, preparation_v1, composed_v1, registration_v1.
- all_def_v1 was interrupted, has no completed report, and was not resumed.
  Process inspection confirmed its worker was absent before starting all_def_v2.
- all_def_v2 completed all 15 comparisons and GLB exports in 124.19 seconds.
  All 80 serialized frames passed parity, maximum vertex error 3.8753e-7.
- Preparation preserves original rest geometry/topology/UVs. Identity skinning
  maximum error is 4.4409e-16; research skin SHA is
  3b37e368db98f20d0141f1713cee50abd802cd3e4467e0c239ab7def616f647f.
- Quality: restShape passed; idleAppearance, depthUnclipped and animatedSurface
  failed. Eleven animated vertex samples exceeded camera depth bounds.
- Movement/attack GIFs were posted. The wolf lacks source extension and the
  rider's sword sweep is incomplete. Ownership boundaries still stretch in
  probes. The result is not accepted simply because playback parity passes.

The 124.19 seconds is fitting/preview/export processing only. Existing two-actor
capture cost 88.38 seconds and was reused. Registration cost 3.76 seconds.
Anatomy authoring, investigation, tests and review wall time are separate.

After review, builder validation was tightened and rigid serialization derived
from the selected profile. A real rerun in authoring_v2_validation differs from
authoring_v1 ONLY in builderSha256; all 19 composition arrays are exactly equal.
The original artifact hashes were not rewritten. All four volume rules hit
vertices (861, 262, 91, 564). Ten authoring, four identity, six preparation and
eight composition tests passed (28 total). Preparation tests emitted existing
unclosed-image ResourceWarnings in evaluation.py; no test failed.
The Stronghold inventory validator still covers all 21 configured units.

## Boar Rider Identity Rejection

The source at V:/homm3_unity_work/Assets/CustomUnits/homm3_lab/toa_boar_rider/
OwnedSkinned/Source/master.glb exists but is NOT a verified Boar mesh.
Its SHA is affadbe581298cf73e28e3c17f0b0c7db989fe75542758eb48138e0d5ee89a3f.
It has the same 57 joints, 12,863 vertices and 15,122 triangles as Raider.
Both GLBs have identical binary payload SHA
db500c28b00b3619ad98fd22114e03e4f95fdc2794ea390803aecedeec0accd5,
and identical accessor, mesh and embedded-image definitions (root verified).
Independent CPU audit confirms identical decoded skin/texture/mesh arrays.
The extra Orientation node rotates rest-world coordinates to (-z, y, x);
it does not turn the wolf into a boar. That source is rejected as a mislabeled
placeholder. No source or installed bundle was changed. A genuine Boar mesh
remains outstanding; do not close the roster by substituting this duplicate.
