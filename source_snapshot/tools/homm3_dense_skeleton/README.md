# Dense multi-angle bone consensus (hobgoblin pilot)

Pose authority: **3D consensus** from dense high-saturation bone overlays generated at multiple
camera angles from **NN-upscaled** HoMM3 sprites, then projected to sprite-2D for a Mixamo fit check.

## Locked pilot choices

| Knob | Value |
|------|-------|
| Generator | Cursor `GenerateImage` (pilot only — **not** unit-scale) |
| Pose/identity ref | `canonical_group_11_nn_upscale/` (~1024 edge, shared-crop **nearest-neighbor**, not GenAI) |
| Consistency ref | **Previous generated overlay** (art + neon skeleton) on every job after the first |
| Product | 3D consensus → sprite-2D keypoints → optional keypoint fit check |
| Swap later | Replace generation with ComfyUI; keep digitize/cull/consensus contracts |

## Overlay legend (fail-closed if too desaturated)

- **cyan** — spine / head
- **lime / magenta** — arm pools (strike side = nearer **orange mace tip**, never trust L/R color)
- **yellow** — hips + legs
- **orange** — mace shaft + tip
- **text labels** — every joint dot gets a small high-contrast name tag using exact spellings:
  `Nose, Neck, RShoulder, RElbow, RWrist, WeaponTip, LShoulder, LElbow, LWrist, MidHip, RHip, RKnee, RAnkle, LHip, LKnee, LAnkle`

## Camera angle ids (`source_manifest.json`)

| id | Azimuth | Elevation | Full samples |
|----|---------|-----------|--------------|
| `iso` | 40° | 30° | 4 |
| `side` | 90° | 15° | 4 |
| `front` | 0° | 20° | 3 |
| `rear_q` | 140° | 25° | 3 |

= **14 overlays/frame** at full density (**112** for this 8-frame clip).

## Agent generation checklist (GenerateImage) — required

Ordered jobs live in `out_dense_skeleton_g11/generation_plan.json` (from `build_generation_plan.py`).

For **each** job, in order:

1. **Refs (always):**
   - Primary: `canonical_group_11_nn_upscale/frame_XX.png` (large NN sprite — do **not** use the tiny padded DEF canvas)
   - Secondary (if `hasPrevOverlay`): the previous job’s `dest` overlay (same neon legend + character)
2. **Prompt:** use the job’s `prompt` field from `generation_plan.json` (built by `prompt_contract.py`). It requires faithful pose, neon sticks, **and named joint labels** with exact spellings. When a previous overlay is attached, lock identity + skeleton + label style to that image.
3. Save to the job `dest` path (`overlays/fXX/{angle}/sample_YY.png`)
4. After the batch: `python tools/homm3_dense_skeleton/run_pilot.py` then `preview_consensus_overlay.py`

Do **not** generate overlays from the raw 450×400 padded DEF frames — character is only ~40–80 px there.

## Sprite projection target

1. Shared union crop + integer nearest-neighbor enlarge (`upscale_sprites_nn.py`, target edge ≥900)
2. Body-normalize angles before triangulation
3. Map iso sample → sprite via silhouette bbox (`project_sprite_2d.py --mode iso_sil`)

## Commands

```bash
python tools/homm3_dense_skeleton/upscale_sprites_nn.py --target-edge 1024
python tools/homm3_dense_skeleton/build_generation_plan.py
# …agent GenerateImage per generation_plan.json…
python tools/homm3_dense_skeleton/run_pilot.py
python tools/homm3_dense_skeleton/preview_consensus_overlay.py
```

## Generator swap point

`run_pilot.py` never calls an image API. Any backend that writes the overlay path contract
(and preferably honors the same sprite+previous-overlay refs) can replace Cursor GenerateImage.

## Proof boundaries

- Overlays / digitize / cull / 3D / 2D: **generated artifact validated**
- Mixamo side-by-side: check only — **attack-read unproven**
- Unit-scale / ComfyUI: **not claimed**
