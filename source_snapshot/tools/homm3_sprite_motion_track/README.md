# Visual-match pose contract (sprite ↔ mesh)

## Contract

1. **Left panel (sprite)** is visual ground truth under the fixed HoMM3 iso camera.
2. **Success** = absolute **chroma / pixel** match on the **same pixel grid** (mesh rendered at sprite WxH with the same camera). Position is absolute — no root/scale pose normalize.
3. **Only appearance normalize allowed:** color-palette alignment if mesh textures drifted from the source. Not a pose normalize.
4. **Joints are a tool**, not the success metric. They help the optimizer find poses and keep animation smoother once keyframes exist. Passing joint error does **not** mean success.
5. Long-travel landmarks (weapon tip, etc.) must be found by **automated color + pattern matching**, not by a human painting every frame, and not by fabricating rigid wrist offsets.
6. If absolute chroma/pixel match cannot be met, that is an upstream failure (track, mesh, camera framing). Fail closed.

## Pipeline stages

| Stage | Role |
| --- | --- |
| Mesh clean | Weld Meshy duplicate verts, cut mace/hair rubber-band bridges, clean weapon weights (`repair_meshy_prop_bridges.py` on UniRig combat master) |
| Motion articulation (pilot) | Dense tracks → rigid **parts** + **hinges** from multi-frame motion (`discover_articulation_from_motion.py`). Topology-free; not humanoid joint names. |
| Part→mesh map + DOFs | Project parts onto master mesh under visual-match camera; pose with **relative-to-f0** root cam-plane translate + hinge rotations about the camera axis, soft-weighted (`map_articulation_to_mesh.py`). |
| Seed + track | Automated landmarks (LK/NCC + color/pattern reacquire for high motion) — legacy humanoid seed path |
| Marker IK fit | Primary: grab skinned mesh vertices and drag them to sprite landmarks; bones solve as secondary. Each frame keys grabs from the **previous posed mesh**, then warps from that pose. On the UniRig combat master, frame 0 can be bind; on the **A-pose+mace** master, frame 0 must be solved (bind ≠ attack). Tip-far frames solve **strike-arm DOFs only** (spine/legs locked out) with torso-flip rejects so unreachable tips cannot fold the body as a 2D cheat. |
| Absolute refine | Optional chroma polish (Workbench warm loop + jolts) |
| **Absolute match** | **Proof / fail-closed gate** |
| Preview GIF | Human view only — not the gate |

## Commands (hobgoblin g11 pilot)

### UniRig combat master (preferred — weld + bridgefix)

```bash
python tools/homm3_sprite_motion_track/track_joints_lk.py \
  --out-dir artifacts/hobgoblin_attack_pose_pipeline/out_sprite_motion_track_g11_visual_match/track

OUT=artifacts/hobgoblin_attack_pose_pipeline/out_sprite_motion_track_g11_meshy46_v4_visual_match/fit_check
mkdir -p "$OUT/sprite_landmarks"
cp artifacts/hobgoblin_attack_pose_pipeline/out_sprite_motion_track_g11_visual_match/track/keypoints.json \
   "$OUT/sprite_landmarks/keypoints.json"
tools/.venvs/homm3_dwpose/Scripts/python.exe tools/homm3_silhouette_pose_fit/run_fit.py \
  --config tools/homm3_silhouette_pose_fit/configs/h3_hobgoblin_attack_g11_sprite_motion_track_meshy46_v4_visual_match.json \
  --skip-infer
```

### A-pose + attached mace (alternate)

```bash
OUT=artifacts/hobgoblin_attack_pose_pipeline/out_sprite_motion_track_g11_apose_mace_visual_match/fit_check
mkdir -p "$OUT/sprite_landmarks"
cp artifacts/hobgoblin_attack_pose_pipeline/out_sprite_motion_track_g11_visual_match/track/keypoints.json \
   "$OUT/sprite_landmarks/keypoints.json"
tools/.venvs/homm3_dwpose/Scripts/python.exe tools/homm3_silhouette_pose_fit/run_fit.py \
  --config tools/homm3_silhouette_pose_fit/configs/h3_hobgoblin_attack_g11_sprite_motion_track_apose_mace_visual_match.json \
  --skip-infer
```

Gate config lives under `absoluteMatch.failClosedMaxChromaMae` / `failClosedMaxRgbMae`.

### Motion articulation discovery (topology-free pilot)

```bash
tools/.venvs/homm3_dwpose/Scripts/python.exe \
  tools/homm3_sprite_motion_track/discover_articulation_from_motion.py \
  --frames-dir artifacts/hobgoblin_attack_pose_pipeline/source_attack_frames/canonical_group_11_nn_upscale \
  --out-dir artifacts/hobgoblin_attack_pose_pipeline/out_articulation_motion_g11
```

Outputs `frame_00_parts_hinges.png` + `articulation_report.json` + `tracks.npz` (rigid parts + hinge candidates from multi-frame motion; no humanoid joint names).

### Map parts onto mesh + part/hinge DOFs

```bash
tools/.venvs/homm3_dwpose/Scripts/python.exe \
  tools/homm3_sprite_motion_track/map_articulation_to_mesh.py \
  --articulation artifacts/hobgoblin_attack_pose_pipeline/out_articulation_motion_g11/articulation_report.json \
  --out-dir artifacts/hobgoblin_attack_pose_pipeline/out_articulation_motion_g11/mesh_map
```

Writes `mesh_parts_hinges_f00.png`, per-frame `frames/side_XX.png`, `articulation_parts_posed.glb`, and `mesh_articulation_report.json`. Pose DOFs are motion-part hinges (not UniRig role names). Absolute chroma match remains unproven.

## Proof

Generated-artifact validated for tooling. Attack-read / OE runtime **unproven**.
