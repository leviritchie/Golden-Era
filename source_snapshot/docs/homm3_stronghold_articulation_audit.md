# Stronghold Articulation Audit

Follow-up: [original T2 full-animation repair](homm3_t2_full_animation_repair.md)
covers every available Ogre Mage and combined Boar Rider source group using
their existing binds, rather than the isolated mount's synthetic test.

2026-09-12. Bounded diagnostic follow-up to the assisted animation pilot. No
production selection, animation, weights, or installed payload changed.

## Why The Diagnosis Changed

Bad deformation does not by itself establish fused geometry. This audit compares
source mesh connectivity separately from saved-animation deformation, rather than
asking another generation to fix every visible failure.

The Ogre Mage staff shaft is a separate exact-position component (456 triangles),
and the ornament is separate too. Reviewed views show arm/torso clearance. There
is no demonstrated unwanted staff/body or arm/torso bridge. A generated neutral
body reference was prepared but no replacement Ogre T2 request was made.

The Boar Rider has one 5,097-triangle shared-welded-edge face component spanning
both mount and rider body. This is stronger evidence than a shared material/node
or point-only contact. Exact actor junctions remain unlocalized; coincident seams
versus a continuous authored surface are not fully distinguished. A mount-only
candidate is justified as an isolated experiment, not a proven animation fix.

## Independent Binding Failure

CPU replay held topology and recorded motion fixed and changed only initial versus
refined skin weights. Principal stretch is a local surface length multiplier.

| Candidate | Worst refined stretch | Same face with initial weights | Maximum with initial weights elsewhere |
| --- | --- | --- | --- |
| Ogre Mage | 13.83 | 1.20 | 8.27 |
| Boar Rider | 25.45 | 1.57 | 18.09 |

The Boar's worst triangle mixes left forearm and right upper-arm ownership. The
support producer admits nearby bones across regions, and the consumer treats
region labels as soft. This is not necessarily an out-of-support implementation
error: the present search space permits damaging redistribution. Initial weights
also fail elsewhere, so reverting to them is not an accepted solution.

These measurements prove a weight-induced worsening on the reported triangles,
not that all defects have the same cause or that the source meshes are sound.

## Bounded Component Experiment

One mount-only T2 candidate was generated for 15 Meshy credits. Its reference removes the rider
and weapon, exposes four legs, and reconstructs the obscured back. It is an
identity-conditioned generated image, not an original HoMM3 sprite. Equipment
and rider generation are deferred; this is not a completed mounted assembly.

The resulting mesh has 7,382 vertices and 8,571 triangles. Actual textured
four-view/turntable renders show the mount with visible leg clearance and no
rider. Its saddle and tusks are disconnected components. The exact-position
audit found zero nonmanifold edges; this does not prove complete geometric health.

A cheap quadruped rest-template placement was attempted without source capture,
image fitting, or manually authored joint coordinates. The two-view overlay
failed visual preflight: head/tail positions are above the anatomy, hind feet
terminate above the hooves, and lateral leg placement is too narrow. The proposed
small-motion test was therefore NOT RUN. No synthetic articulation GIF or motion
quality claim is produced from this rejected placement. The turntable is camera
movement around an unrigged mesh, not skeletal animation.

At the user's subsequent explicit request to try animation despite the imperfect
placement, `articulation_trial_v2/` runs the unchanged prepared bind through 50
synthetic frames: opposing front-leg swings, then opposing hind-leg swings, at
10 degrees each way. The original refusal is preserved. Its `articulation.gif`
shows actual skeletal deformation in fixed side and rear views, not a turntable
or a sprite-derived gait. The preparation overlay's second-view "Front" label
is incorrect for this camera; it observes the rear.

The zero-angle motion reconstructs the rest mesh within 1.25e-16 and bone lengths
remain fixed within 5.56e-17. Visible leg motion is present, but hindquarter
deformation and local strain remain; the trial is not quality accepted. There
were no manual joint edits, optimizer run, or additional generation charges.

The original refusal was not an animation-ready result. A more anatomical,
repeatable rest-placement method is still needed. Do not infer that this placement
failure condemns the new mesh, or manually rescue it and call the workflow cheap.

Artifacts and exact provenance:

- `artifacts/homm3_mocap_v2/stronghold_articulation_audit_v1/`: connectivity,
  initial/refined replay, hashes, component projections, and suspect triangles.
- `artifacts/homm3_mocap_v2/boar_mount_open_v1/`: reference, prompt, single task
  identity, candidate outputs, and `articulation_v1/` rejected rest overlay.
  Generation or a turntable is not articulation acceptance.
- `artifacts/homm3_mocap_v2/ogre_open_neutral_v1/`: unused reference and prompt;
  no paid T2 generation for Ogre in this iteration.

## Scope And Scaling

This iteration does not add a production gate or a universal mesh-repair system.
Connectivity and strain are complementary diagnostic signals, not sufficient
automatic anatomical acceptance tests. Modest-vision review packets should expose
these signals and allow explicit uncertain/reject decisions without expert
coordinate authoring. That low-cost operating model is not yet demonstrated.

Six synthetic connectivity tests pass, including point-only contact versus shared
edges, collapsed-face rejection, and float32-induced false-contact rejection.
The three actual source meshes pass those numerical guards. Independent review
checked the diagnostic math and proof claims; no production behavior changed.

## Existing Surface-Repair Trial

At the user's request, `boar_mount_open_v1/surface_repair_trial_v1/` reuses the
existing `run_skin_mesh_pilot.optimize` repair-only stage on the exact 50 synthetic
frames from `articulation_trial_v2`. Only skin weights change. Rest geometry,
topology, UVs, texture, skeleton, joint motion, and comparison cameras are fixed.
The compatible `TopologyWeightField` keeps exact-position welds and admits only
the original nonzero influence support. It does not introduce nearby opposite
limbs as new candidates. This is not the old rigid-attachment split operation,
nor a replay of an identical historical solver configuration.

The unchanged shared objective combines surface constraints and weight
prior/smoothness. Image fitting, rest-mesh adjustment, and a motion-retention
objective are disabled. The existing optimizer still evaluates an unused actual
rest-render target with a zero photo coefficient. No production source changed.

All 150 iterations completed in 8.54 seconds of optimization, excluding setup and
comparison rendering. This is not an end-to-end fleet throughput measurement.

| Full 50-frame diagnostic | Before | After repair |
| --- | --- | --- |
| Maximum triangle principal stretch | 10.194 | 3.038 |
| Minimum triangle principal stretch | 0.0214 | 0.2837 |

Fixed baseline limb memberships retain 92.6-99.0% of peak mean displacement and
93.4-102.4% of displacement energy. Repair does not simply freeze the limbs, but
these magnitude checks do not prove direction/phase fidelity or a good gait.
The before/after GIF presents unchanged-motion side and rear views, with before
on the left and repair on the right. Improvement is local and visually subtle;
the knowingly imperfect rest placement and severe residual strain remain.

CPU/GPU baseline reconstruction agrees within 9.50e-8, initial field playback
within 8.95e-8, and repaired zero-angle rest identity within 6.16e-8. Weight
normalization, original support, unchanged rest vertices, source hashes, and
saved baseline strain were checked. Five existing surface-constraint tests and
nine weight-field tests pass. The report pins the current solver code and saved
candidate weights. No additional generation, export, or deployment occurred.

This is generated diagnostic evidence that the existing surface repair is useful
on this test, not animation acceptance or production pipeline integration. Keep
it as the repair candidate and test source-driven motion with proper rest
placement before broadening the run. Do not replace it with a third repair system
or hide the remaining faults behind a passing average metric.
