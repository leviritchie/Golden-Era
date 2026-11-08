# Town full-3D: SDXL-inpainted back layers (experiment, 2026-09-29) — measured negative

**Proof tier:** generated artifact / offline moderngl render. Nothing was bundled or installed. The candidate
`fa_v9_sdback` was deleted after review; the script and sheets remain.

## Question

The user's framing: the problem is not the shape of the landscape objects but what is behind them. Could inpainting
build the hidden layers, painting the terrain behind occluders?

## Method (`tools/homm3_town_scene_meshes/town_full3d_sdback.py`)

The pass is texture only, on top of `fa_v8_mirror` (layered fill + mirror closure, `docs/homm3_town_mirror_closure.md`).

- **Mask.** Every texel the LDI's image quilting had synthesised in the back layers (`Mesh_Back_Terrain`, `_Far`,
  `Mesh_Back_TerrainNear_0`). These are exactly the texels hidden at rest, so the rest frame stays byte-identical by
  construction (0 texels changed outside the mask).
- **Inpainting.**
  - Model: the lane's local SDXL inpaint model (`town_full3d_sdfill` settings).
  - Prompt and negative: the Factory profile's `TEX["sd"]`.
  - Scale and windows: half texel scale, 1024x768 windows.
  - Colour grade: per-channel mean and std, matched to the quilted fill.
- **GPU gate.** SDXL runs through `town_full3d_gpu.gate`, with an 8 GB VRAM need sized to the smaller windows (the
  sdfill runs need 11 GB at 1536x1024).

## Result

Geometry is unchanged, so the streak metrics are identical to `fa_v8_mirror`. Judged by eye in the sweep zooms, all
three runs were **worse than the quilted fill**:

1. **Strength 0.92, 3-px mask growth.** Flat grey blotches throughout. Below strength 1.0 the pipeline starts masked
   areas from its grey placeholder, and the small scattered islands never recover. Sheet:
   `artifacts/claude_takeover_20260927/review/factory_sdback_v1_s092_vs_mirror.png`.
2. **Strength 1.0, 8-px growth.** Pale, blocky, sky-coloured patches instead of rock or sand.
3. **Strength 1.0, the mask closed by 24 px** into whole ridge-shaped regions (the "background plate" form). The
   patches are larger and still pale haze, plus one near-black blob. Sheet:
   `artifacts/claude_takeover_20260927/review/factory_sdback_vs_mirror.png`.

## Why

- **The context is haze.** In this painting, what surrounds each hidden region is mostly distant, hazy mesa and sky.
  SDXL continues that faithfully, so the "ground behind the ridge" comes out as flat pale haze, which reads as holes
  once revealed next to saturated near rock.
- **The quilt copies real far-side texels.** Its colour and grain are the painting's own.
- **Texture was not the dominant defect anyway.** At the reachable sweeps, what is visible is mostly geometric
  stretch: the band along rest rays, and old depth-mesh building slabs. A better texture cannot fix that.

## If revisited

Inpaint depth as well as colour, and condition on near-ground exemplars rather than the whole window. Candidates are
a depth-conditioned ControlNet, or an image prompt taken from the ridge's own far-side ground. Keep the quilt as the
baseline to beat.
