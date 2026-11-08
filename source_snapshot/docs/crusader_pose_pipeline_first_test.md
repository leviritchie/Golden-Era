# Crusader 2D→3D pose pipeline (first test)

**Unit:** Castle Crusader (`h3_crusader`, `CCRUSD.def`)  
**Proof bar:** generated-artifact + human preview. Absolute chroma gate remains fail-closed until it passes. OE / Golden Era import unproven.

## Artifact root

`artifacts/crusader_pose_pipeline/`

| Subdir | Contents |
|--------|----------|
| `idle_f0_painted/` | GenerateImage + chroma postpass Meshy-ready idle f0 |
| `out_meshy_t2_idle_f0/` | Meshy T2 8k PBR mesh + auto-rig + bridgefix |
| `source_frames/` | Native 80-frame corpus + NN upscales |
| `out_articulation/` | Full-corpus articulation discovery |
| `out_track/` | Manual seed + LK track (silver blade tip) |
| `out_fit/idle_attack_front/` | Marker IK bake + preview + absolute match |
| `out_fit/joint_audit_bind/` | Bind multi-angle joint audit (contact sheet + report; batch preflight) |

## Locked Meshy settings

- `ai_model=meshy-t2`, `model_type=smart-topology`, `target_polycount=8000`
- `should_texture=true`, `enable_pbr=true`
- `remove_lighting` omitted (`removeLightingMode=omitted_unsupported_on_smart_topology`)

## Commands (re-run)

```bash
# Meshy master + one auto-rig
python tools/homm3_meshy_frame_pose/generate_meshy_t2_unit_master.py

# Articulation on full NN corpus (sequential frame_*.png)
PYTHONIOENCODING=utf-8 python tools/homm3_sprite_motion_track/discover_articulation_from_motion.py \
  --frames-dir artifacts/crusader_pose_pipeline/source_frames/nn_upscale_seq \
  --out-dir artifacts/crusader_pose_pipeline/out_articulation

# Bridge-fix Mixamo sword arm (no dedicated tip bone)
"V:/Games/actionmesh/tools/blender-3.5.1/blender.exe" -b \
  --python tools/homm3_silhouette_pose_fit/repair_meshy_prop_bridges.py -- \
  --src artifacts/crusader_pose_pipeline/out_meshy_t2_idle_f0/rigged/idle_f0_rigged.glb \
  --out artifacts/crusader_pose_pipeline/out_meshy_t2_idle_f0/rigged/idle_f0_rigged_bridgefix.glb \
  --report artifacts/crusader_pose_pipeline/out_meshy_t2_idle_f0/diagnostics/bridgefix_report.json \
  --weapon-bones mixamo_sword --tip-bone RightHand --wrist-bone RightHand \
  --elbow-bone RightArm --head-bone Head --min-bridge-faces 0

# Track idle+attack (after soft-shadow cull + seed + tip overrides)
PYTHONIOENCODING=utf-8 python tools/homm3_silhouette_pose_fit/cull_def_soft_shadow_frames.py \
  --src-dir artifacts/crusader_pose_pipeline/source_frames/nn_upscale_idle_attack \
  --min-culled-per-frame 1
PYTHONIOENCODING=utf-8 python tools/homm3_sprite_motion_track/track_joints_lk.py \
  --seed artifacts/crusader_pose_pipeline/out_track/seed/seed_joints_f00.json \
  --sprite-dir artifacts/crusader_pose_pipeline/source_frames/nn_upscale_idle_attack \
  --out-dir artifacts/crusader_pose_pipeline/out_track/track \
  --tip-profile silver_blade \
  --overrides artifacts/crusader_pose_pipeline/out_track/overrides_tip_neck.json

# Fit (expects keypoints already staged under out_fit/.../sprite_landmarks/)
python tools/homm3_silhouette_pose_fit/run_fit.py \
  --config tools/homm3_silhouette_pose_fit/configs/h3_crusader_idle_attack_front_meshy_t2_marker_ik.json \
  --skip-infer
```

## First-run results (generated-artifact)

| Stage | Result |
|-------|--------|
| Painted idle f0 | OK — `idle_f0_painted/meshy_ready/frame_00.png` |
| Meshy T2 8k PBR + auto-rig | OK — task `019fe2e0…` / rig `019fe2e2…`; `remove_lighting` omitted |
| Articulation (80 NN frames) | OK — 6 parts / 11 hinges |
| Sword bridgefix | OK — Mixamo Right* arm; LeftHand weights empty on this export |
| Track idle+attack | OK — silver_blade + tip/wrist/neck overrides |
| Marker IK bake | OK — meshy-6 master; `frame0_root` + `collisionBias` (maxStepRad off); meanLossPx≈34 |
| Absolute chroma gate | FAIL (expected prior) — not re-run on this collision-bias fit |
| Preview GIF | OK (human judgment) — `out_fit/idle_attack_front/preview/attack_g11_side_by_side.gif` |
| Lit 60fps preview | OK — `preview_lit_60fps/crusader_idle_attack_lit_60fps.mp4` (noshadow + speedups; promoted from `compare_noshadow/plant_collision`) |
| Soft-shadow cull | Required before seed/track — `cull_def_soft_shadow_frames.py` (idle+attack culled **182124** px across 15 frames) |

## Noshadow A/B (generated-artifact)

After soft-shadow cull, first noshadow fit regressed (~49 mean). Track Nose hold fixed (Neck seed offset) + IK speedups, then re-ran prior knobs:

| Variant | meanLossPx | fit sec | max tip px | Lit |
|---------|------------|---------|------------|-----|
| plant + collision (current) | **39.80** | **182** | 177 | `compare_noshadow/plant_collision/…mp4` |
| plant, collision OFF | 39.80 | 169 | 177 | `…/plant_nocollision/…mp4` |
| hips locked | 42.08 | 183 | 229 | `…/hips_locked/…mp4` |
| frame0_root | 42.12 | 195 | 228 | `…/frame0_root/…mp4` |

Prior shadowed log means (not re-lit): hips_plant≈36.8, authored≈39.5, collision-era≈34.2, first noshadow≈49.0.  
Speed: ~182s vs ~412s for the pre-opt noshadow fit (~2.3×). Collision on/off matched MAE here (accept-only prior after Jacobian change) — use lit for fold-through judgment. Summary: `compare_noshadow/comparison_summary.json`.

Attack-read and OE runtime remain **unproven**.

## Remaining DEF groups (batch)

Runner: `tools/homm3_silhouette_pose_fit/batch_fit_crusader_def_groups.py` (parallel fits, alpha-snap seeds, authored `bone_dofs_crusader_*_gN.json`).  
Runs **bind multi-angle joint audit** first (`run_joint_audit.py` → `out_fit/joint_audit_bind/`); fails closed on collapsed role landmarks.  
Idle g2 + attack front g12 already proven in `out_fit/idle_attack_front/`. Other present CCRUSD groups land under `out_fit/gNN_<name>/`.

## Notes

- Meshy auto-rig for this export is **24-bone Mixamo**, not UniRig-46. Bone roles: `tools/homm3_silhouette_pose_fit/bone_roles_crusader_meshy_t2.json`.
- `LWrist` maps to **`LeftHand` bone head** (LeftHand skin weight may be 0.0 — still the correct landmark; `skinBoneExtras.LWrist` includes `LeftForeArm` for grab verts). Do not collapse LWrist onto `LeftForeArm`/`LElbow`.
- Bind joint audit: `py -3 tools/homm3_silhouette_pose_fit/run_joint_audit.py` (iso/front/side/back/top contact sheet).- Active master GLB: meshy-6 textures on pristine rig + **RightHand-only** bridge fix (`rigged/idle_f0_rigged_meshy6_bridgefix_hand.glb`). Broader mixamo_sword bridge delete punched blade holes and split islands.
- `collisionBias` treats disconnected mesh islands as geodesically distant (so sword↔body contacts are scored even after prop detach).
- Mesh-bind camera projection missed the NN sprite crop; idle f0 seed was manually gated on the sprite (`out_track/seed/seed_manual_overlay.png`).
- `identityFrame0` is **false** because bind≠sprite registration.
- Absolute chroma gate stays fail-closed (RGB MAE failed this run; chroma MAE was under threshold).
- Preview GIF is for human judgment only and was rendered after the gate failed.
- Marker IK now bakes/exports the animated GLB (previously only wrote pose vectors).
- `markerIk.groundAnchor.mode=frame0_lateral_lowest_foot` (crusader): keep root world XY at frame 0 (no ice-skate) and plant the lowest foot on frame-0 ground Z after each solve so Hips crouch cannot lift/sink the mesh. `frame0_root` (full root freeze) and `lowest_foot` remain available.
- `markerIk.groundAnchor.mode=frame0_root` pins overall root translate (`rt/ru/rf`) to the frame-0 solved position and freezes those DOFs during later solves (hobgoblin configs unchanged / off by default). `lowest_foot` remains available.
- `markerIk.collisionBias` soft-penalizes geodesically distant mesh samples that come too close (depth/self-intersection prior). Tested independently of `maxStepRad` (step cap left at 0 on this crusader run).
- `markerIk.midlineBias` kept in code but **disabled** for crusader after hard-reject experiments fought tip CCD. Prefer authored per-clip Euler DOFs instead.
- `markerIk.boneEulerAxesSchedule` — hand-authored per-bone free Euler axes (`x|y|z`) per animation band. Idle: [`bone_dofs_crusader_idle_g2.json`](../tools/homm3_silhouette_pose_fit/bone_dofs_crusader_idle_g2.json). Attack front: [`bone_dofs_crusader_attack_front_g12.json`](../tools/homm3_silhouette_pose_fit/bone_dofs_crusader_attack_front_g12.json). Locked axes are pinned to the warm-start value (fail-closed).
- `markerIk.maxStepRad` hard-caps per-bone Euler change vs the previous frame when enabled; available for separate A/B.
- Post-fit playback polish: `smooth_marker_pose_vectors.py` (Gaussian Euler smooth + extrema restore + windup time-stretch) → `fit_report_smoothed.json` for lit 60fps preview without re-solving IK.
- Sword/open-boundary repair: `fill_mesh_holes.py` (holes_fill/edgeloop_fill; no remesh).
