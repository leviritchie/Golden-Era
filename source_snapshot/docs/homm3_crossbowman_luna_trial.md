# Crossbowman Luna Trial

## Outcome

This bounded trial is **partial and supervised**, not a successful autonomous full repair.
The single successful lane is the textured Meshy 7.1 T-pose body-only fit in
`mesh-fitted-v2`. The prop recipes were rejected after textured multi-angle isolation showed
that they selected a narrow rod/quiver-like region while the main waist crossbow remained, or
included the quiver and red skirt patch. The default manifest therefore has no prop attachment.

## Reproducible Inputs

- Original registered source mesh: `artifacts/meshy_downloads/h3_crossbowman_smartrigged.glb`
  SHA-256 `2af77608c061088711789acd694a1b011ce64e9678001dc363224fc482d44f4b`.
- Saved capture and motion: `artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/runs/h3_crossbowman`.
- Paired source registration: `.../runs/h3_crossbowman/linked_master/idle0_registration.json`.
- Source image: `artifacts/creature_aaa_3d_upscale/h3_crossbowman.png`.
- Selective Meshy task: `01a0bd89-8d35-7215-9379-f5c0cfc4f45a`, model `meshy-7.1`, variant
  `t-pose`, standard mode, target polycount 8000, texture/PBR/remesh, no auto-rig, no T2.
- Successful candidate: `artifacts/meshy_downloads/meshy71_repair_candidates/h3_crossbowman/t-pose/mesh.glb`
  SHA-256 `96a82d5b4fed1c87c555975392f1178e83a293a6bc15e0a11259927b84e30b8c`.

The primary manifest is `tools/homm3_meshy_frame_pose/crossbowman_meshy71_tpose_pilot.json`.
It points directly at the paired registration report; `load_similarity` accepts the existing
registration schema and verifies its selected candidate instead of requiring an untracked
wrapper. The abandoned registered-idle adapter and its untracked pilot test were removed.

## Exact Commands

Candidate generation was the one selective regeneration used in this trial:

```powershell
py -3 tools/homm3_meshy_frame_pose/generate_meshy71_repair_candidates.py generate `
  --unit h3_crossbowman --variant t-pose --polycount 8000 --timeout-s 1800
```

Body review and the default full reel:

```powershell
py -3 tools/homm3_meshy_frame_pose/fit_mesh_rest_pipeline.py `
  --manifest tools/homm3_meshy_frame_pose/crossbowman_meshy71_tpose_pilot.json `
  --units h3_crossbowman --review

py -3 tools/homm3_meshy_frame_pose/fit_mesh_rest_pipeline.py `
  --manifest tools/homm3_meshy_frame_pose/crossbowman_meshy71_tpose_pilot.json `
  --units h3_crossbowman --preview
```

The focused verification command is:

```powershell
py -3 -m unittest tools.homm3_meshy_frame_pose.test_mesh_rest_fit `
  tools.homm3_meshy_frame_pose.test_rest_retarget `
  tools.homm3_meshy_frame_pose.test_prop_attachment `
  tools.homm3_meshy_frame_pose.test_fit_mesh_rest_pipeline `
  tools.homm3_meshy_frame_pose.test_reel_meshy71_candidate
```

## Visual Evidence

Best default output, body-only full reel:

![Crossbowman Meshy 7.1 T-pose body-only reel](../artifacts/meshy_downloads/meshy71_repair_candidates/h3_crossbowman/mesh-fitted-v2/animation_reel.gif)

Source textured comparison reel:

![Registered source comparison reel](../artifacts/meshy_downloads/meshy71_repair_candidates/h3_crossbowman/source-textured-review/full_reel.gif)

The accepted body overlay and keyframes are `mesh-fitted-v2/rest_overlay.png` and
`mesh-fitted-v2/keyframes.png`. The failed registered-idle comparison remains in
`mesh-fitted-v1/rest_overlay.png` and `mesh-fitted-v1/keyframes.png`. The rejected prop
diagnostics are in `mesh-fitted-v3/`, especially `prop_isolation_review.png`,
`current_prop_multiview.png`, and `union_weapon_isolation.png`.

## Timing And Gaps

- Meshy 7.1 generation and polling: about 147 seconds observed.
- T-pose body review: 9.76 seconds on the first run; 9.97 seconds on the direct-registration
  rerun. The final default 71-frame preview took 64.16 seconds wall time; its generated report
  records 63.01 seconds of pipeline time.
- Rejected prop review/preview: 9.85 / 74.11 seconds. These timings are diagnostic only.
- Baseline focused suite: 46 tests passed. Parent review then removed a silent single-candidate
  selection fallback from direct-registration loading and added selection regression tests.
  Final verification: 50 focused tests passed, including mixed-schema selection handling.

The first implementation correctly found a missing registered-idle prerequisite, but a refusal
and source replay was not completion; parent redirection was required to add the bounded adapter
before the visual gate could be applied. The registered source was provenance-valid but visually
misaligned: yaw-90 elbow/forearm behind the arm, feet outside boots, skull above helmet, and
shooting shoulder/torso stretch with hands at the belt. The visual gate correctly rejected it.
Selective Meshy 7.1 T-pose regeneration then produced the usable body lane.

The remaining workflow gap is expert prop selection. Luna did not reliably identify the full
crossbow stock plus both limbs versus the rear quiver, rod, and cloth in the textured views.
This trial does not establish that the geometry cannot be separated by the shared solver.
No new mocap, per-frame edits, silent fallback, deployment, or runtime/gameplay
proof was used. The final claim is therefore body-fit success with supervised prop work still
required, not a completed crossbow repair.
