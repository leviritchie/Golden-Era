# Mounted mesh identity correction

Status: identity verified from user correction and direct textured renders on
2026-09-06. The corrected candidate `wolf_rider_corrected/all_def_v2` completed
in 85.3998897 seconds but was rejected by the quality gate for idle appearance
and animated-surface failures; it is not approved for delivery.

## Authoritative mapping

| Semantic unit | Download filename | Appearance |
| --- | --- | --- |
| Wolf Rider | h3_wolf_rider_smartrigged.glb (sha 2fb1bb07...; was named h3_wolf_raider_* until 2026-09-27) | Unhelmeted rider, gray wolf |
| Wolf Raider | h3_wolf_raider_smartrigged.glb (sha b15de4cf...; was named h3_wolf_rider_* until 2026-09-27) | Helmeted rider, dark wolf |

`mounted_asset_identity.py` owns the semantic paths and SHA-256 pins. The files
were renamed on 2026-09-27 so the basename matches the unit (2026-09-27: the two files were renamed so each basename now names its own unit; pre-swap bytes and note in `artifacts/meshy_downloads/_superseded_do_not_use/wolf_identity_swap_20260927.note.json`.) The evidence sheet and hash readback are under
`artifacts/homm3_mocap_v2/skin_mesh_pilot/wolf_identity_audit/`.

The correct Wolf Rider mesh has 8,162 vertices and 58 source joints; the mesh
previously used has 12,863 vertices and 57 source joints. Bone names do NOT carry
the same anatomical meaning between these meshes. A copied numerical map is
invalid, not an optimization. Corrected anatomy needs independent inspection.

## Invalidated pairing

The historical `skin_mesh_pilot/wolf_rider` authoring, camera registration,
composed motion, full-DEF fitting, topology-weight candidates, and strike
correction used Wolf Rider sprites with the Wolf Raider target mesh. The
`shape_preserved/h3_wolf_rider` frozen preparation is internally consistent but
belongs to that wrong pairing. These files remain immutable diagnostic evidence;
they are not accepted preparations for either semantic unit.

Raw sprite extraction and actor captures remain source evidence. They must be
recomposed against the corrected owned bind before use. Old fitted weights,
mesh corrections, anatomical bone indices, cameras, and error thresholds must
not silently transfer to the other mesh.

Identity validation is wired into target loading, mounted preparation, and the
legacy mounted profile getter. The frozen loader calls that getter through its
existing original-mesh check. Wrong-pairing preparation and fit now fail closed
before new work starts. Direct diagnostic readers of historical NPZ files remain
available; they are not a delivery route. No game deployment was changed.

## Strike experiment before correction was reported

`screen_landmark_ik.py` provides a reusable fixed-length, selected-branch rotation
fit using SciPy, source-authored screen points, and explicit rigid weapon sites.
Mount transforms, inactive local rotations, first source frame, and all context
frames were held exact. Bone lengths were preserved. The original mesh and all
skin weights were fixed during this motion test.

The seven authored attack frames are in `wolf_rider_strike_landmarks.json` with
ordered source-image hashes. Targets are hip-relative and proportion-calibrated,
not absolute silhouette coordinates. The solve took 6.02 seconds and reduced
mean landmark error from 22.50 to .17 preview pixels. The rendered blade swing
improved, but the torso folded poorly. This is explicitly NOT a visual quality
pass, and the later identity discovery further invalidates promotion of this
unit-specific result. Do not tune it further against the wrong mesh.

Verification: 70 focused/regression tests passed, including fixed-length
multi-frame IK and negative identity checks; the two additional roster tests
also passed. Both mesh hashes were read back. A Luna review checked the new
identity gates. The 21-entry Stronghold inventory validates roster coverage,
configured SIDs, and existence of listed evidence, not animation completion.

The corrected anatomy, owned preparation, and recomposition are now generated
under `skin_mesh_pilot/wolf_rider_corrected`; the `all_def_v2` fit remains
rejected. See `CORRECTED_WOLF_RIDER_AND_GOBLIN.md` for this later result.
Next: diagnose the remaining source-to-motion mismatch on that corrected input.
Keep fixed-motion skin/mesh fitting as a separate stage; use source-supported
weapon motion constraints only where capture demonstrably lacks the action.
