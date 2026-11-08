# HoMM3 Meshy per-frame pose smoke

Drive the **master UniRig mesh** with poses from Meshy image-to-3D + auto-rig donors (one sprite frame → one posed donor → nearest-bone keyframe).

## Smoke (frame 00 only)

```bash
# From repo root; MESHY_API_KEY from env or root .env
tools/.venvs/homm3_dwpose/Scripts/python.exe \
  tools/homm3_meshy_frame_pose/run_smoke_frame00.py
```

Texture matrix (stop at first SUCCEEDED auto-rig):

1. Meshy textured generate + `input_task_id` rig  
2. Untextured generate + sprite albedo bake + `model_url` rig  
3. Untextured + master projection bake + `model_url` rig  
4. Untextured + solid limb-readable albedo + `model_url` rig  

Outputs: `artifacts/hobgoblin_attack_pose_pipeline/out_meshy_frame00_smoke/`

Proof: tooling = generated artifact validated. Attack-read = human judgment on preview only.
