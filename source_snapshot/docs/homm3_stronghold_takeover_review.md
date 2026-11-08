# Stronghold Review, 2026-09-12

Roc exception/refinement work is paused at the user's request. This pass examines
the other 20 Stronghold units before extending the current pipeline. Nothing was
installed, selected for delivery, or visually accepted.

## Evidence

Review directory: `artifacts/homm3_mocap_v2/stronghold_takeover_review_v1/`.
Open `index.html` for per-unit source meshes and selectable saved animations.

- `inventory.json`: 19 explicitly selected non-Roc candidates. All selected
  source-report and corpus hashes matched current files. Boar Rider is excluded
  from the selection; no placeholder animation was substituted.
- `source_mesh_views.json` and `*_source.png`: fresh CUDA renders of each
  unchanged source mesh from four actual angles, with source hashes and nonblank
  checks. These do not apply animation or alter geometry.
- `attack_review_1.png` through `attack_review_3.png`: four sampled front-attack
  frames per unit, showing the source and final selected comparison column.
- The gallery's GIFs replay saved skin-mesh corpus candidates, not fresh fits.
  Hobgoblin and Ogre use their explicitly selected joint-anchor refits; the other
  17 use their selected baseline outputs.

All 19 baseline reports pass rest-shape preservation and fail animated-surface
quality. That establishes neither source-mesh damage nor acceptance of the two
selected refits. Visual inspection of the four-angle source sheets showed no
grossly exploded geometry. Sampled attack frames instead show widespread lost
or shortened weapon, claw, and wing actions. This is a shared motion/attachment
problem to investigate, not a reason to regenerate every source mesh.

Important limitation: all 19 current non-Roc profiles lack `captureBind`. The
current linked-master runner also requires accepted mesh-specific static
registration. This review does not demonstrate that those units have run through
the newer linked-master pipeline. Do not promote the saved corpus GIFs to that
proof tier.

## Targeted Mesh Replacements

Both jobs used `meshy-t2`, `smart-topology`, target 8,000 faces, texture enabled,
PBR enabled, requested 4K textures, and no automatic rigging. Actual charge was
15 credits each, 30 total. Existing assets and profiles were left untouched.

| Unit | Reason | Task | Result |
| --- | --- | --- | --- |
| Ogre Mage | Current mesh visibly mismatches the corrected armored, red-haired, staff-wielding sprite | `01a097ba-087f-7037-b063-08fa156a193a` | 6,896 vertices; 8,059 triangles |
| Boar Rider | No valid selected mesh/capture pair; bounded API recovery could not identify the historical web-generated asset | `01a097ba-85c2-7097-aaa6-64e3ad23d2a0` | 7,087 vertices; 8,452 triangles |

Ogre Mage input is the corrected corpus Idle frame, alpha-cropped with margin
without repainting or resampling. The profile's old `COGRE.dir` source points to
base Ogre and was not used. Boar Rider input is the existing high-detail painted
reference, checked against raw `cboar` imagery for unit identity; it is not raw
sprite-pixel provenance. Its proportions still need acceptance.

Each isolated unit directory contains `generated.glb`, `report.json`, `task.json`,
and `input_crop.png`. Reports preserve input/settings/output hashes without API
keys or signed download URLs. Both GLBs have finite geometry, one material, four
decodable embedded textures, zero skins, and zero animations. Base-color maps
are 4096 square; not every PBR image is 4K.

`preview/turntable.gif` is actual rendered geometry with a moving camera, not
skeletal animation. Generated meshes remain unrigged and unaccepted.

## Next Pipeline Step

The user superseded the proposed Goblin-first order with a direct Ogre Mage and
Boar Rider animation pilot. Its results and intervention record are documented
in `docs/homm3_stronghold_assisted_animation_pilot.md`. Both new meshes were
animated, but the results remain visibly defective and unaccepted. The user
permits LLM assistance while requiring a modest-vision, bounded-cost operating
model for the eventual 200+ unit rollout.

This original review is diagnostic and generated-artifact evidence only. New
linked-timeline animation evidence belongs to the subsequent pilot document;
neither pass establishes deployment or runtime proof.
