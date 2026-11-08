# Crusader Pseudo-Rig Experiment — Handoff

**Status:** parallel experiment lane (not owned-bind / not OE ship)  
**Proof bar:** generated-artifact only — not Unity lab, not OE runtime  
**Date anchor:** 2026-08-10

## Intent

Replace anatomical bind + LLM sticks with a deliberately stupid flat proximity pseudo-rig:

- 48 `deform_NNN` handles under one `ROOT`
- k=4 inverse-distance² skin weights
- Optimize per-frame handle TR against HoMM3 sprite silhouettes
- One shared mesh/bind/weights; many pose vectors; bake ordinary skinned GLB + Actions

Product hope: OE sees a mundane `SkinnedMeshRenderer` + clips, not VAT/Gaussian.

This lane does **not** replace [`.cursor/skills/homm3-pose-pipeline/SKILL.md`](../.cursor/skills/homm3-pose-pipeline/SKILL.md) or the owned rigid crusader bind.

## Verdict (read this first)

| Version | What worked | What failed |
|---------|-------------|-------------|
| **v0** (`L_alpha` only, per-frame bbox normalize) | Optimizer moves handles; combat-core mean IoU **0.49 → 0.71**; GLB/Actions bake | Visually **melted idle blobs** — IoU rises without clean limb articulation |
| **v1** (clip-shared framing + `L_edge` + `L_dt`) | Tooling landed; edge/DT in loss; clip-shared targets; resize-paste placement fixed | Death probe final IoU **0.577** (vs v0 death ~0.62) — still **not clean articulation**; do not full combat-core yet |

**Conclusion:** alpha-only pseudo-rig cannot deliver good articulation. Edge/DT is the right next lever, but v1 is **not proven** yet. Do not run a full combat-core v1 pass until a death (or attack) strip looks articulated.

## Tools

| Piece | Path |
|-------|------|
| Build 48-handle master | [`tools/homm3_pseudo_rig/build_pseudo_rig.py`](../tools/homm3_pseudo_rig/build_pseudo_rig.py) + [`run_build_pseudo_rig.py`](../tools/homm3_pseudo_rig/run_build_pseudo_rig.py) |
| Host fit launcher | [`tools/homm3_pseudo_rig/run_pseudo_rig_fit.py`](../tools/homm3_pseudo_rig/run_pseudo_rig_fit.py) |
| Blender fitter | [`tools/homm3_pseudo_rig/blender_pseudo_rig_fit.py`](../tools/homm3_pseudo_rig/blender_pseudo_rig_fit.py) |
| v0 targets | reuse [`tools/homm3_silhouette_pose_fit/prepare_targets.py`](../tools/homm3_silhouette_pose_fit/prepare_targets.py) |
| v1 targets | [`tools/homm3_pseudo_rig/prepare_targets_v1.py`](../tools/homm3_pseudo_rig/prepare_targets_v1.py) |
| v0 config | [`tools/homm3_pseudo_rig/configs/h3_crusader_combat_core_pseudo_rig.json`](../tools/homm3_pseudo_rig/configs/h3_crusader_combat_core_pseudo_rig.json) |
| v1 config | [`tools/homm3_pseudo_rig/configs/h3_crusader_combat_core_pseudo_rig_v1.json`](../tools/homm3_pseudo_rig/configs/h3_crusader_combat_core_pseudo_rig_v1.json) |
| Camera | [`tools/homm3_silhouette_pose_fit/homm3_pose_camera.py`](../tools/homm3_silhouette_pose_fit/homm3_pose_camera.py) (`axis: iso`, crusader `orthoScale: 4.2`) |

Blender: `V:/Games/actionmesh/tools/blender-3.5.1/blender.exe` (has scipy).  
Host Python: system `py -3` (broken `tools/.venvs/homm3_dwpose` — do not use).

## Artifacts

### Pseudo-rig master (shared)

| Asset | Path |
|-------|------|
| Master GLB | `artifacts/crusader_pose_pipeline/pseudo_rig/owned_bind/crusader_pseudo_master.glb` |
| Handle catalog | `artifacts/crusader_pose_pipeline/pseudo_rig/owned_bind/handle_catalog.json` |
| Source mesh | `artifacts/crusader_pose_pipeline/out_meshy_t2_idle_f0/meshes/idle_f0_meshy6_retexture.glb` |

48 farthest-point handles, flat under `ROOT`, k=4 proximity point weights. Audit: 6972 verts, no empty groups.

### v0 combat-core fit (completed)

| Asset | Path |
|-------|------|
| Fit report | `artifacts/crusader_pose_pipeline/pseudo_rig/out_fit/fit_report.json` |
| Comparison strip | `artifacts/crusader_pose_pipeline/pseudo_rig/out_fit/comparison_strip_per_clip.png` |
| Per-clip GIFs | `artifacts/crusader_pose_pipeline/pseudo_rig/out_fit/gifs/` |
| Pose vectors | `artifacts/crusader_pose_pipeline/pseudo_rig/out_fit/poses/pose_XXX.npy` |
| Export GLB | `artifacts/crusader_pose_pipeline/pseudo_rig/export/crusader_pseudo_rig.glb` |
| Clip map | `artifacts/crusader_pose_pipeline/pseudo_rig/export/clip_map.json` |
| Log | `artifacts/crusader_pose_pipeline/pseudo_rig/out_fit/fast_fit_v2.log` |

**v0 metrics (generated-artifact):**

- Rest mean IoU **0.493** → final mean IoU **0.709**
- Pose norms ~**1.2–2.7** (handles actually move after NM fix)
- Per-clip final IoU roughly: idle 0.89, move 0.68, attacks ~0.67–0.70, hit 0.64, defend 0.74, death 0.61

**Visual read:** middle row of the strip still looks like a standing/melted figure for non-idle clips. IoU wins ≠ articulation.

Combat-core clips (~60 frames): idle g2, move g0, attack front/up/down, hit, defend, death.

### v1 probes

| Run | Path | Notes |
|-----|------|-------|
| attack+death (sparse remap) | `…/out_fit_v1_attack_front_g12_death_g5/` | mean IoU ~0.52; silhouettes **pixel-shredded** — obsolete |
| death-only (resize-paste) | `…/out_fit_v1_death_g5/` | final IoU **0.577**; rest mean 0.322 → Stage A 0.543; strip/GIF exist; still blobby vs target sword/lean |

Killed early runs: rest-anchored registration (scale ~3×) — ignore those metrics.

**v1 death gate not passed:** comparison strip middle row does not read as a clear death lean/collapse relative to the sprite; treat as tooling proof + weak silhouette lift only.

## Critical bug already fixed (do not regress)

Scipy Nelder-Mead on **all-zero** `x0` uses `zdelt ≈ 2.5e-4` → invisible handle motion → identical poses.

**Required:** bound-scaled `initial_simplex` + `randomProbesPerBlock` translation probes before NM (see `_optimize_frame` in `blender_pseudo_rig_fit.py`). First “fast fit” without this was worthless; killed deliberately (exit 1).

## Solver shape (locked)

- **DOF:** per handle `[plane_u, plane_v, depth, rx, ry, rz]` in camera-relative armature space; plane-biased bounds
- **Stage A:** per-clip sequential warm-start; weak deform/stretch; no neighbor term
- **Stage B:** block-coordinate polish with `L_neighbor` + deform/stretch
- **Not** one giant DE over all frames × handles

v0 loss: `L_alpha + λ_t L_neighbor + λ_d L_deform + λ_s L_stretch`  
v1 loss adds: `λ_e L_edge` (Sobel) + `λ_dt L_dt` (symmetric distance transform)

v1 target framing: **clip-shared union bbox** (`prepare_targets_v1.py`) so limb swings occupy different canvas regions.  
v1 pred placement: `predPlacement: match_target` — per-eval scale/align raw render to that frame’s target (not rest-anchored).

## How to run

```bash
# Build master (once)
py -3 tools/homm3_pseudo_rig/run_build_pseudo_rig.py

# v0 full combat core (known completed; long)
py -3 tools/homm3_pseudo_rig/run_pseudo_rig_fit.py --fast

# v1 probe (preferred until visuals look articulated)
py -3 tools/homm3_pseudo_rig/run_pseudo_rig_fit.py --v1 --fast --clips death_g5
py -3 tools/homm3_pseudo_rig/run_pseudo_rig_fit.py --v1 --fast --clips death_g5,attack_front_g12

# Smoke wiring only
py -3 tools/homm3_pseudo_rig/run_pseudo_rig_fit.py --smoke
```

`--clips` forces fresh targets and writes under `out_fit_v1_<clips>/` (or `out_fit_<clips>/` for v0).

## Explicit non-goals (still)

- No LLM sticks, no anatomical `bone_roles`, no Mixamo
- No change to owned rigid master / live crusader bundle
- No OE deploy / Unity lab import until a separate request
- Color/feature appearance loss not implemented yet (plan deferred past edge/DT)

## Next agent: recommended order

1. **Open** `artifacts/crusader_pose_pipeline/pseudo_rig/out_fit_v1_death_g5/comparison_strip_per_clip.png` and `gifs/death_g5_silhouette.gif` — confirm articulation still insufficient (current judgment: yes).
2. Improve deformation structure before another long fit, pick **one**:
   - Translate-only Stage A, then unlock rotation; raise `lambdaDt` / `lambdaEdge`
   - Rigidity clusters / handle kNN as soft bones (limits melt)
   - Extra handles on extremities (sword tip, feet, head) with higher influence
3. Re-probe `--v1 --fast --clips death_g5` until the strip reads as death, not a standing melt
4. Then attack_front probe → only then full `--v1 --fast` combat-core → `export_v1/`
5. Unity lab import is a **separate** milestone (mirror owned-skinned lab; new PseudoRig lane)

## Fail-closed notes

- Stage A must beat rest **mean** IoU by +0.01 before Stage B (smoke exempt)
- Empty vertex groups / weight-sum errors fail the master build
- Do not present LK/track or Mixamo work as this experiment
- Label all claims **generated-artifact** until OE smoke exists

## Relation to owned-bind lane

Owned crusader skinned delivery remains the active ship path (`docs/crusader_owned_bind_skinned_mesh_handoff.md`). Pseudo-rig is an alternate deformation model experiment. Keep artifact trees separate under `artifacts/crusader_pose_pipeline/pseudo_rig/`.
