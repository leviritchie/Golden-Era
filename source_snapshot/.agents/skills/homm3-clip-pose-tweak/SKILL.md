---
name: homm3-clip-pose-tweak
description: >-
  Inspect, freeze, and rotate GPU cascade clip keyframes, then unlit-preview
  the edited poses without rerunning search. Use when an agent should manually
  tweak gpu_clip_result.json joints, zero false travel on a bone/frame range,
  or raster a sprite|mesh overlay of those edits.
---

# GPU clip pose tweak (no search)

Edit an existing cascade `gpu_clip_result.json`. This is **not** the owned-bind /
fixed-length IK delivery pipeline, and it is **not** a new fit.

- Keep/zero and physics are not invoked.
- Intentional travel is not scaled.
- `CURRENT_CASCADE_KEEP` stays closed.

## Workflow

1. **Inspect** (CPU). Lists parent/child names and which frames each joint travels.
2. **Probe** (CUDA, one frame). Tries ±axis on named joints so you can see which axis moves a limb. Occupancy IoU is a diagnostic, not the keep score.
3. **Apply** (CPU). Freeze or rotate named joints. Writes a new clip directory.
4. **Preview** (CUDA raster only). Sprite | unlit mesh | occupancy overlay GIF at 180 ms/frame.

**Judge the edit by whether the clip reads like the source animation** (lean, flap, stride, still idle). The Meshy mesh will not match the 1999 sprite pixel-for-pixel; do not chase leftover red/blue on the overlay. Do not keep a move only because occupancy IoU rose, and do not reject a move that matches the animation because occupancy IoU fell.

Never point `--out` at the source clip folder.

```bash
py -3 tools/homm3_silhouette_pose_fit/tweak_gpu_clip_poses.py inspect \
  --clip <arm>/gpu_clip_result.json \
  --mesh artifacts/meshy_downloads/<unit>_smartrigged_rigidized.glb

py -3 tools/homm3_silhouette_pose_fit/tweak_gpu_clip_poses.py apply \
  --clip <arm>/gpu_clip_result.json \
  --ops ops.json \
  --mesh artifacts/meshy_downloads/<unit>_smartrigged_rigidized.glb \
  --out artifacts/pose_picker_runs/clip_pose_tweaks/<name> \
  --preview
```

`--preview` on `apply`, or the `preview` / `probe` subcommands, take the exclusive cascade GPU lock. Inspect/apply without `--preview` do not.

```bash
py -3 tools/homm3_silhouette_pose_fit/tweak_gpu_clip_poses.py probe \
  --clip <arm>/gpu_clip_result.json \
  --mesh artifacts/meshy_downloads/<unit>_smartrigged_rigidized.glb \
  --frame 12 \
  --bones Bone_024,Bone_029,Bone_000,root_rotation,root_translation \
  --delta-deg 20
```

`--frames 0-7` on preview rasters a subset. For idle-prefixed clips, keep one rest pose (`copy_frame` from 0 onto the idle prefix/suffix) and preview `0,8-20` rather than eight identical idle plates.

## ops.json

Degrees for bone/root rotation. Body lengths for root translation. Bone `x`/`y`/`z` in `gpu_clip_result.json` are degrees (same contract as root `camera_*`); do not paste radian magnitudes into `delta_deg`.

```json
{
  "operations": [
    {
      "op": "freeze",
      "bones": ["Bone_006"],
      "frames": "0-7",
      "source": "previous",
      "include_descendants": true
    },
    {
      "op": "rotate",
      "bone": "Bone_019",
      "frames": [8, 9, 10],
      "axis": "x",
      "delta_deg": -12
    },
    {"op": "copy_frame", "from": 0, "frames": "1-7"},
    {"op": "set", "bone": "Bone_006", "frames": "0-7", "x": 0, "y": 0, "z": 0}
  ]
}
```

| op | Required | Notes |
|----|----------|--------|
| `freeze` | `bone`/`bones`, `frames`, `source` | `previous` / `bind` / `frame:N`. Frame 0 cannot use `previous`. |
| `rotate` | `bone`, `frames`, `axis`, `delta_deg` | Bone axes `x,y,z`. Root: `bone: root_rotation`, axis `camera_forward` / `camera_right` / `camera_up`. |
| `set` | `bone`, `frames`, at least one axis | Absolute degrees (bones/root rotation) or body lengths (`root_translation`). |
| `copy_frame` | `from`, `frames` | Whole pose, including root. |
| `translate_root` | `frames`, `axis`, `delta` | Axis `forward` / `lateral` / `vertical`. |

`include_descendants` needs `--mesh`. Unknown joint names fail closed. Over-limit rotations fail closed.

## After preview

Read the unlit mesh GIF first (`solved_rgb/gpu_solved_rgb.gif` or the middle preview panel). Compare that motion to the sprite frames. Overlay red/blue is a hint for direction, not a score to maximize.

Proof is generated-artifact + preview only.

Do not claim OE battle runtime. Do not treat a tweak as a cascade search result.
