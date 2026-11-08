# Meshy 7.1 Repair Lane

> The Archer bind-selection and rebase claims below are superseded experimental history, not
> demonstrated repairs. The skeleton was not fitted to the regenerated mesh, and reducing the
> rebase to joint positions discarded its rotation correction. Use
> [Mesh-fitted rest rigs](homm3_mesh_rest_fit_pipeline.md) for the current Archer fit and reel.
> The Meshy generation commands remain available; do not use the historical selection as quality
> acceptance or the historical reel as the repaired output.

## Purpose

The Meshy 7.1 lane is a selective geometry repair for units whose owned-bind audit identifies a
repeatable mesh defect, especially a weapon or accessory fused into the body. It is not a replacement
for the reference-derived owned bind and it is not run for every unit.

Meshy contributes a surface candidate only. The repository-owned skeleton, position-keyed weights,
scale policy, replay audit, and delivery decision remain authoritative. A Meshy vendor armature is
never used as animation authority.

## Routing

1. Run the existing source mesh through the geometry preflight and canonical-T-pose owned-bind audit.
2. Route only a repair-class unit to a small Meshy 7.1 portfolio. The current candidate generator
   supports `source`, `a-pose`, and `t-pose`; the first repair pilot uses standard `meshy-7.1`,
   approximately 8,000 triangles, 4K textures, PBR enabled, no auto-rig, and image enhancement off.
3. Preflight every candidate after exact-position welding. Raw exporter boundary counts are not a
   topology verdict; welded boundary, welded non-manifold edges, and connected components are.
4. Bind the candidate with `bind_meshy71_candidate.py`. For a T-pose candidate, the bind pose is a
   canonical T-pose generated from the registered reference skeleton with bone lengths preserved.
   A source-pose candidate uses `--bind-pose registered-reference`; it is never passed through the
   synthetic T-pose rest frame.
5. Run `select_meshy71_candidate.py`. A candidate is selected only if it remains one welded component,
   does not grow boundary or non-manifold defects beyond the geometry budget, reduces reference-replay
   escape by at least 10%, and does not increase reviewed stretch edges or worst stretch.
6. If selected, the candidate is still only a generated-artifact candidate until the upstream
   reference blockers are repaired and the normal installed/runtime proof chain is completed. If not
   selected, retain the source owned-bind route; do not silently fall back to a different Meshy model.

## Pilot Evidence

The two-unit pilot demonstrates why this is a selector rather than a blanket regeneration:

| unit | candidate | welded surface | max escape | reviewed stretch edges | worst stretch | route |
| --- | --- | --- | ---: | ---: | ---: | --- |
| `h3_archer` | Meshy 7.1 T-pose | 1 component; 35 boundary; 36 non-manifold | 5.90% | 728 | 8.73x | selected for reference repair |
| `h3_archer` source bind | source mesh | 1 component; 74 boundary; 32 non-manifold | 8.87% | 1,276 | 34.47x | comparison baseline |
| `h3_cavalier` | Meshy 7.1 T-pose | 1 component; 186 boundary; 218 non-manifold | 49.41% | 1,940 | 16.73x | rejected |
| `h3_cavalier` source bind | source mesh | 1 component; 133 boundary; 89 non-manifold | 5.62% | 2,185 | 21.10x | comparison baseline |

The source rows in this table are the original Meshy surfaces passed through the same canonical-T-pose
bind, so the comparison isolates geometry rather than changing both the mesh and the bind policy at
once. The Archer result is a meaningful geometry improvement, but both units still report
reference/plate blockers. Those blockers are not hidden by the selector: `audit.ok` remains false and
the selection report carries the upstream issue list.

An additional Archer source-pose Meshy 7.1 regeneration was tested through the registered-reference
bind. It produced a cleaner welded surface (`13` boundary and `25` non-manifold edges), but the
deformation selector rejected it: escape improved only `2.77% -> 2.68%`, while reviewed stretch edges
grew `22 -> 24` and worst stretch grew `2.70x -> 3.97x`. This is why the selected Archer route is the
T-pose candidate rather than the superficially cleaner source-pose mesh.

## Commands

```powershell
py -3 tools/homm3_meshy_frame_pose/generate_meshy71_repair_candidates.py generate `
  --unit h3_archer --variant t-pose --polycount 8000

py -3 tools/homm3_meshy_frame_pose/score_meshy71_candidate.py `
  --mesh artifacts/meshy_downloads/meshy71_repair_candidates/h3_archer/t-pose/mesh.glb `
  --out artifacts/meshy_downloads/meshy71_repair_candidates/h3_archer/t-pose/geometry_preflight.json

py -3 tools/homm3_meshy_frame_pose/bind_meshy71_candidate.py `
  --unit h3_archer --variant t-pose `
  --mesh artifacts/meshy_downloads/meshy71_repair_candidates/h3_archer/t-pose/mesh.glb `
  --run-dir artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/runs/h3_archer `
  --output-dir artifacts/meshy_downloads/meshy71_repair_candidates/h3_archer/t-pose/bind `
  --emit

py -3 tools/homm3_meshy_frame_pose/reel_meshy71_candidate.py `
  --run-dir artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/runs/h3_archer `
  --source-bind artifacts/meshy_downloads/meshy71_repair_candidates/h3_archer/baseline-registered/owned_bind_h3_archer_registered-source.glb `
  --candidate-bind artifacts/meshy_downloads/meshy71_repair_candidates/h3_archer/t-pose/bind/owned_bind_h3_archer_t-pose.glb `
  --source-report artifacts/meshy_downloads/meshy71_repair_candidates/h3_archer/baseline-registered/bind_h3_archer_registered-source.json `
  --candidate-report artifacts/meshy_downloads/meshy71_repair_candidates/h3_archer/t-pose/bind/bind_h3_archer_t-pose.json `
  --out-dir artifacts/meshy_downloads/meshy71_repair_candidates/h3_archer/t-pose/reel-reference-space `
  --yaw 40
```

The corrected Archer reel is the reference-space comparison across the ten non-bookend clips:
`artifacts/meshy_downloads/meshy71_repair_candidates/h3_archer/t-pose/reel-reference-space/yaw040/archer_master.gif`.
The source panel uses its registered-reference bind. The candidate panel uses the canonical-T-pose
bind and re-bases each captured frame through `D = G * C^-1`, rather than driving a T-pose mesh with
idle-rest coordinates. The master contains 64 actual clip frames; the six sequence bookends are not
silently replaced by idle frame zero. In the generated report, the candidate has lower worst edge
stretch than the registered source on 9 of 10 clips. This is experimental animation evidence, not
installed-game proof.

The common-frame control can be generated with:

```powershell
py -3 tools/homm3_meshy_frame_pose/archer_reference_space_experiment.py `
  --run-dir artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/runs/h3_archer `
  --source-bind artifacts/meshy_downloads/meshy71_repair_candidates/h3_archer/baseline-registered/owned_bind_h3_archer_registered-source.glb `
  --candidate-mesh artifacts/meshy_downloads/meshy71_repair_candidates/h3_archer/t-pose/mesh.glb `
  --out-dir artifacts/meshy_downloads/meshy71_repair_candidates/h3_archer/reference-space
```

That experiment manufactures the original source's T-pose control and a source-weight transfer
variant on the Meshy surface. The transfer variant is intentionally separate from the reel until its
motion-conditioned skin is competitive; it is a search surface for the next Archer improvement,
not a silent replacement.

The selection report is the promotion decision, not the generated GLB by itself. The shipped
animation lane remains the exact-reference owned bind until this report, the reference audit, and
the normal deployment/runtime gates all pass.

Proof classification for this lane is intentionally limited to **generated artifact validated**.
Neither Meshy task completion nor a passing geometry preflight proves an installed or user-visible
animation result.
