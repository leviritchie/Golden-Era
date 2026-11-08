# Full-Set Captured-Mocap Rollout

The source/static roster is the output of
`tools/homm3_meshy_frame_pose/audit_homm3_mesh_coverage.py` and currently
contains 275 units.  It reports 246 canonical SmartRigs, 29 meshes without a
named SmartRig, and no completely missing meshes.  The 29 are the pinned T2
boar rider plus 28 textured Meshy-7 meshes under
`artifacts/meshy_downloads/meshy7_missing/`; every one now has a separate,
non-promoted Blender candidate.  The latest addition is a Luna
quantization-aware retry for `h3_sharpshooter`; the explicitly pinned Luna
retry for `hota_cove_nix_praetorian` and the other envelope candidates remain
unaccepted until deformation and animation checks pass.  The Blender task may
leave a candidate failed closed; a structural round-trip pass is not animation
acceptance.

`experiments/homm3_mocap_v2/run_all_mocap_pipeline.py` is the current-mocap
inventory and runner.  It emits one row for every source slot, records exact
corpus and registration hashes, and only emits a `weights_only` command when a
captured corpus, registered camera, frozen preparation, and canonical
SmartRig all exist.  Custom Blender rigs are recorded as candidates and are
never silently substituted for the canonical SmartRig.  Duplicate captures
and registrations require an explicit preference; an experimental directory
name is not treated as quality evidence.  The Wolf Rider/Raider
filenames were swapped on disk on 2026-09-27 so each basename names its own unit (no
coverage alias any more); the mounted Wolf Rider uses `h3_wolf_rider_smartrigged.glb` (sha 2fb1bb07) with the corrected
mounted preparation and composed corpus, rather than mixing the legacy mesh
with corrected offsets.

The runner is intentionally bounded:

```powershell
C:/Python312/python.exe experiments/homm3_mocap_v2/run_all_mocap_pipeline.py
C:/Python312/python.exe experiments/homm3_mocap_v2/run_all_mocap_pipeline.py --unit h3_behemoth --run-unit --seconds 120 --iterations 120
C:/Python312/python.exe experiments/homm3_mocap_v2/run_all_mocap_pipeline.py --run-ready --max-units 3 --seconds 120 --iterations 120
```

`--run-ready` is a sequential, bounded batch.  It records completed,
failed, and already-existing outputs in `homm3_mocap_batch_run.json`; a failed
unit never falls back to a different mesh or motion lane.

The current inventory resolves to 20 `ready_for_weights_only` units, 29
`custom_rig_pending` units, and 226 other `pending` rows.  The Roc is in the
ready set after its explicit `registration_v1_auto` camera registration.  The
Wolf Rider is also runnable after selecting the corrected mounted branch; its
previous fail-closed error was a real bind mismatch between the legacy corpus
and corrected preparation, not a fitter failure.  These are planning states,
not quality grades.

The generated inventory is source/static planning evidence.  A candidate GIF
is generated-artifact evidence only.  Lighting is a separate delivery stage:
after a fit passes its own gates, derive `approved-oe-v1` soft lighting from
the immutable raw solve with `prepare_ingame_lighting.py`; do not treat a fit
preview as a deployed or game-visible result.

## Full-set source preparation status

The upstream source extraction is now complete for all 275 real inventory
rows.  `tools/homm3_import/extract_all_creatures.py` records this in
`artifacts/homm3_mocap_v2/full_set_source_extract_v3/report.json` with
`ok=true`; every row has a battle DEF PNG sequence and sidecar JSON in the
ignored Unity working tree under
`oldenera_factions/Assets/CustomUnits/homm3_lab/<unit>/extracted_battle/`.
This proves source materialization only.  It does not mean the units have
captured mocap corpora, registrations, frozen skin preparation, fitted poses,
quality acceptance, bundles, or runtime proof.

The idle-0 mocap lane consumes those original `GG_FF.png` plates as one
native reel. Custom-rig candidates remain blocked until their rig reports are
accepted. Bundling is paused: the source roster is complete, but the mocap-fit
and acceptance stages are not.

## Canonical full-set scheduler

The automatic full-set motion lane is idle-0 linked-master mocap, not
silhouette pose search. `tools/homm3_silhouette_pose_fit/run_full_set_scheduler.py`
reads the coverage manifest, selects only `smartrig_present` rows, and runs
`experiments/homm3_mocap_v2/run_full_set_mocap_unit.py` per unit:

- one DEF reel with a single idle bookend between shipped clips
- unshipped groups (turns, vertical attack/shoot) recorded and not captured
- camera and frozen bind from idle DEF group 2 frame 0, because the Meshy
  meshes were generated from that plate
- existing SmartRig as the idle-0 surface; Mixamo 25-joint capture unless a
  frozen donor already exists; Beholder remains unsupported
- custom/Astra candidates stay excluded until their separate rig gate passes

A failed unit does not stop unrelated units. Resume requires the idle-0 mocap
child report, not a pose-search clip ledger. The live ledger is
`artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/`. Pose-search artifacts under
`full_set_canonical_v1/` are leftover from the previous lane and are not this
scheduler's resume input.

The scheduler is still a motion-fit stage. Successful child reports are
generated-candidate evidence, not lighting approval, Unity bundles, or runtime
proof. Bundling remains a final step after every canonical and custom unit has
an accepted fit, an `approved-oe-v1` soft-lighting artifact, and delivery/runtime
validation.

Idle-0 registration is a floor column: undo Mixamo 45° facing, pin every
ground-contact joint to the mesh floor, height-scale to the mesh top, yaw
until the floor footprint fits, then XZ-only suction up the column.
`linked_master_ground` is an opt-in experiment (floor drop + uniform height
scale only) and is not the live idle-0 default. Mocap
still owns later-frame relative swings. Human cleanup of a finished
idle-0 bind uses `tools/homm3_mocap_cleanup/server.py`. It exposes
pipeline-owned knobs (global similarity, bind-offset length scale, per-vertex
weight set, influence trim) and writes
`artifacts/homm3_mocap_v2/cleanup_edits/`. It does not overwrite scheduler
runs, does not pose individual bones, and is not ship. Contract:
`docs/homm3_mocap_cleanup_editor.md`.

The previous silhouette ledger selected 244 of 246 canonical SmartRigs and was
stopped before Ancient Behemoth finished. That pose-search work is not mocap
proof and is not resumed.

Custom Meshy-7 units still have unaccepted Blender envelope candidates. Visual
inspection of the 29 stills is in
`artifacts/homm3_mocap_v2/meshy7_astra_batch/custom_rig_inspection.json`.
The important template corrections (not yet re-exported) are: Ice/Frost reuse
the coiled-mermaid template, Sacred Phoenix reuses Phoenix, Nymph/Oceanid use
a standing-gown mermaid template, and Nomad/Boar use a rider-mount template
instead of biped/quadruped AABB.

`tools/homm3_silhouette_pose_fit/prepare_extracted_soft_lighting.py` now
provides the corresponding source-extracted lighting adapter.  It takes an
exact source GLB, an explicit raw `solve_unit_light_palette.py` solution, and a
hash-pinned DEF frame directory; it creates a separate neutral matte GLB,
applies the existing `oe-gentler-lighting-v3` energy redistribution, and
bakes a candidate texture.  Its manifest keeps
`visualProfileAccepted=true` separate from `unitQualityAccepted=false` and
`runtimeAccepted=false`.  It intentionally does not fabricate the captured
mocap selection fields used by the older stronghold-only lighting script.

`tools/homm3_silhouette_pose_fit/run_extracted_lighting_stage.py` wraps that
adapter for the canonical coverage: it discovers and hash-stages all extracted
DEF plates for each unit, runs the raw palette solve, then applies the approved
soft-lighting transform with per-unit resume/failure state.  Its dry run
currently resolves all 246 canonical units and their source plates.  It is
sequenced after mocap fit, not run concurrently, because both stages use the
shared GPU.

## Hand-authored exception lane

When a Meshy envelope is structurally unusable, a Luna Blender task may write a
candidate beside the original failed report.  The current
`hota_cove_nix_praetorian` retry is pinned explicitly in
`audit_homm3_mesh_coverage.py`; its relaxed envelope distance is recorded in
the retry report and is not a global threshold.  The coverage audit exposes
that file as a `luna_blender_envelope_retry` candidate, while the rollout
runner still requires a canonical SmartRig and a registered corpus before it
can execute mocap.  No hand-authored candidate is promoted, selected for
runtime, or treated as animation-quality evidence without the same deformation
and visual gates as the automatic lane.

The first bounded hand-authoring probe on the Behemoth failed closed because
the exported SmartRig did not expose semantic distal-forelimb groups.  That is
the desired failure mode: a future Blender task must first establish a
source-verified region map before touching weights, rather than inferring
regions from generic vertex indices.

The corrected Wolf Rider branch has now been reviewed by Luna using the move
and idle previews.  The mounted pair reads as an articulated wolf plus rider
with no catastrophic collapse or mirror; the candidate is still rejected by
the automatic quality gate because the tiny weapon region creates a high-strain
interface and the full surface remains above the deformation threshold.  No
manual weights were changed.  If a cleanup is needed, the bounded next edit is
a provenance-pinned weight-only mask for rider/mount contact, distal wolf
limbs, and the rider weapon, followed by the same export and deformation gates.
Luna's bounded weapon-only trial is recorded at
`artifacts/homm3_mocap_v2/hand_authored_trials/h3_wolf_rider_weapon_v1/report.json`:
all 27 weapon vertices are already exactly 1.0-owned by the rider's right
hand, while 99 adjacent rider-arm vertices carry partial right-hand influence.
Because changing that boundary would edit body vertices without a reviewed
geometric mask, the trial correctly made no edit and remains unpromoted.

Pikeman exposed a different, presentation-only failure: the full-azimuth
silhouette search selected the rear of an asymmetric SmartRig even though the
source sprite is front/three-quarter.  Luna verified that a deterministic
vertical +180 degree yaw wrapper restores the front view in move, idle, and
attack previews without mirroring handedness or changing mocap joints.  The
runner therefore pins `registration_v3_flip180`; this is an explicit camera
correction, not a hand-authored weight edit, and the resulting candidate still
must pass the normal attachment and deformation gates.

## Lighting-stage rollout

`artifacts/homm3_mocap_v2/current_mocap_lighting_selection.json` pins the 20
current ready candidates by fit-report and corpus hash.  The approved
`approved-oe-v1` bake has been generated for all 20 units under
`artifacts/homm3_mocap_v2/lighting_approved_v2/`; its manifests use the
`oe-gentler-lighting-v3` energy-redistributed profile and explicitly declare
that lighting does not own animation authority.  This is generated-candidate
lighting evidence only.  No candidate has yet passed the deformation-quality
gate, and no Golden Era delivery or runtime/gameplay proof is implied.

The read-only `audit_frame_deformation.py` diagnostic now replays serialized
candidate clips and attributes per-frame displacement and triangle strain to
conservative joint regions.  Its batch output is
`artifacts/homm3_mocap_v2/frame_deformation_audit_v1.json`; the current run
covers 188 exportable clips across 11 units, reports high-strain attention
regions without editing any mesh or motion, and records missing-GLB clips as
unavailable rather than silently treating them as clean.

The exporter previously padded some GLB JSON chunks with NUL bytes.  The
internal reader tolerated that, but Blender and other strict glTF readers did
not, which blocked reliable manual inspection.  `eagle_glb.py` now emits
space-padded JSON, and `repair_glb_json_padding.py` repaired 149 older
generated candidate files in place without changing their JSON document,
animation, mesh, or weights.  The repaired Archer candidate imports cleanly in
Blender; its broad Mixamo arm/leg groups are visible, but a manual edit still
requires a reviewed spatial weight-island mask rather than whole-group edits.
Luna produced that reviewable mask at
`artifacts/homm3_mocap_v2/hand_authored_trials/h3_archer_mask_v1/mask.json`
(54 left-arm, 50 right-arm, and 61 distal-leg vertices), but assigned only
medium confidence because Mixamo side labels do not prove which arm holds the
bow in the sprite.  It is deliberately not applied.
