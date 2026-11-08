# Source Weight Region Clipping Trial

## Decision

Diagnostic candidate rejected for promotion. Removing hard anatomical-region
clipping does not recover the missing wing opening on Thunderbird or Shahrokh.
No production preparation, motion policy, export, or runtime payload changed.

## Controlled Comparison

`run_region_clipping_diagnostic.py` reconstructs baseline motion once per clip
and deforms the same mesh with the same joint palettes and inverse binds twice:
first with prepared weights, then with the full source-weight remap. Geometry,
UVs, texture, camera, source frames, and bind remain fixed. Both units cover all
15 groups and 92 authored frames. No fitting or motion adjustment is performed.

`audit_skin_region_clipping.py` requires explicit complete source joint mapping
and identical ordered geometry/material inputs. It rejects rigid attachments,
preserves dense influence counts, and reports whether a candidate meets the
eight-influence delivery limit without quantizing it. Undefined hypothetical
clipped rows are reported explicitly, not replaced with guessed ownership.

## Generated Evidence

Outputs are under `artifacts/homm3_mocap_v2/skin_mesh_pilot/`, respectively
`thunderbird/region_clipping_v1/` and `shahrokh/region_clipping_v1/`.
The reports contain per-frame image and surface scores and every clip has a
comparison GIF and sampled contact sheet. Columns are source, prepared weights,
and unclipped source weights.

| Unit | Mean IoU prepared / unclipped | Mean stretch violation fraction | Mean compression violation fraction |
| --- | --- | --- | --- |
| Thunderbird | 0.548298 / 0.543010 | 0.067851 / 0.082744 | 0.097783 / 0.117314 |
| Shahrokh | 0.534410 / 0.532575 | 0.085644 / 0.098290 | 0.090021 / 0.098146 |

These are frame-weighted means across all 92 frames. Stretch and compression
are the existing reference-triangle principal-stretch metrics, not new gates.
Worst observed stretch drops substantially (312.50 to 11.59 and 249.05 to
16.49), but broader deformation violation fractions increase. Thus preserving
original blends can remove extreme local strain without fixing overall motion
or mesh quality. It is not a general win.

The hypothetical hard-clipped source reconstruction matches each actual
prepared skin to maximum absolute weight error 2.22e-16. This establishes that
the trial is testing removal of that preparation step, not an unrelated weight
replacement. Source blend mass crosses region boundaries on 3,837 Thunderbird
vertices and 4,975 Shahrokh vertices. Shahrokh's remap has nine active influences
on some vertices and is diagnostic-only, not export-eight compatible.

Visual inspection of `g00_move.png` and `g12_attack_front.png` for both units
shows the same deficient wing opening in both mesh columns. Body-adjacent shape
changes are visible but do not restore the source action. This finding rejects
region clipping as a sufficient explanation, not as a possible contributor to
boundary strain.

V1 measured processing time was 12.2691 seconds for Thunderbird and 13.3174
seconds for Shahrokh (25.5865 seconds total). This excludes engineering,
source capture, preparation, optimization, export, and runtime validation.

Final reviewed runs are in each unit's `region_clipping_v2/` directory. They
use the same candidate skin hashes as V1 and enforce every non-weight array
unchanged after serialized readback. Source mesh, captures, frame images, and
diagnostic implementation are hash-pinned and rechecked after rendering.
Both final reports were independently rechecked with zero input hash mismatches.
The final two runs took 13.1765 and 14.2432 seconds (27.4197 seconds total),
separate from V1 and engineering time. Thirteen focused CPU tests passed,
covering complete maps, strict weights, zero allowed support, dense influences,
immutable bind/geometry, and safe ordinary-position corpus inventories.

## Next Constraint

Do not promote unclipped weights or another global motion correction from
aggregate image scores. Remaining investigation must distinguish the actual
articulation represented by captured bone trajectories from how those
rotations act on the mesh's anatomical axes. Preserve this weight-only control
when evaluating that question. Stronghold remains 21 units in scope; this
two-unit diagnostic is not faction completion.
