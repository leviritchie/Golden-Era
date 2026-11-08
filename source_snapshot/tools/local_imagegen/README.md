# Local imagegen (V:-only)

**Install status (2026-08-17):** the local ComfyUI tree at `V:\ml\ComfyUI` and `V:\ml\caches` were deleted to free disk. The scripts in this folder remain. They will fail until ComfyUI is reinstalled at those paths. Do not treat this README as proof that a generator is currently running.

## Choice: ComfyUI

ComfyUI on `V:\ml\ComfyUI` is the local generator for collapse-authentic portrait work when that install is present.

Why this stack:

- Exact width/height are first-class (no accidental 3:4 drift from hosted generators)
- LoRAs, ControlNet, and custom nodes are easy to swap on a 16GB card
- HTTP API at `127.0.0.1:8188` can drive batch candidates for `tools/verify_upscale_collapse_authenticity.py`

Hardware pin: NVIDIA GeForce RTX 5070 Ti (16GB, Blackwell sm_120). Torch must be CUDA 12.8+ with sm_120 support (`torch 2.11.0+cu130` verified; cu130 preferred for Comfy kitchen CUDA ops).

## Layout (all on V:)

| Path | Role |
|------|------|
| `V:\ml\ComfyUI` | ComfyUI source + `.venv` |
| `V:\ml\ComfyUI\models\checkpoints` | Base models |
| `V:\ml\ComfyUI\models\loras` | LoRAs |
| `V:\ml\ComfyUI\models\controlnet` | ControlNets |
| `V:\ml\caches\pip` | pip cache |
| `V:\ml\caches\huggingface` | HF hub cache |
| `V:\ml\caches\torch` | torch hub cache |
| `V:\ml\caches\tmp` | TEMP/TMP |

Do not install models or caches under `C:\`. Use `tools/local_imagegen/comfyui_vdrive.sh` so env vars stay pointed at `V:\ml`.

## Commands

```bash
# GPU / path sanity
bash tools/local_imagegen/comfyui_vdrive.sh env

# Start UI + API
bash tools/local_imagegen/comfyui_vdrive.sh serve

# Pip inside the V: venv (caches stay on V:)
bash tools/local_imagegen/comfyui_vdrive.sh pip install <package>
```

UI: http://127.0.0.1:8188

## Active contract: collapse-authentic master recovery

Two stages (do not collapse into one SD knob sweep):

### Stage A — inverse fill (hard measurement)
Build an HR whose Pillow-NEAREST collapse matches the TwCrPort portrait **exactly**,
without a hidden sample-dot lattice:

```bash
python tools/local_imagegen/optimize_collapse_authentic_hr.py --self-check
python tools/local_imagegen/optimize_collapse_authentic_hr.py \
  --image artifacts/collapse_authentic_upscale/original/h3_hobgoblin.png \
  --out artifacts/collapse_authentic_upscale/candidates/hobgoblin_grid_linear_x16.png \
  --scale 16 --method grid_linear
```

Method: plant portrait RGB at NEAREST sample sites (`S//2`), then interpolate
free pixels through that sample lattice (`grid_linear` default). Exact collapse;
smooth surface through the anchors (no isolated sample dots).

### Stage B — true sparse RePaint invent (modified SD3.5)

Known information is only the Pillow-NEAREST sample lattice. Free pixels must not
be soft-filled beforehand (no Stage A cubic as generative evidence).

- `--init-mode none` — EmptySD3 latent; known sites enter only via RePaint
  `forward_noise(portrait_sample, t)` at `--influence-radius 0`
- `--init-mode sparse_blank|sparse_noise` — plant lattice on black/noise (VAE still
  spatially mixes; prefer `none`)
- `--init-mode stage_a` — legacy soft-evidence init (not true sparse)

```bash
bash tools/local_imagegen/comfyui_vdrive.sh serve
python tools/local_imagegen/sparse_nn_inpaint/__main__.py infer \
  --portrait artifacts/collapse_authentic_upscale/original/h3_hobgoblin.png \
  --out artifacts/collapse_authentic_upscale/candidates/hobgoblin_true_sparse_v1.png \
  --init-mode none --influence-radius 0 --denoise 1.0 --steps 40 --seed 7 --cfg 5.5
```

Judge invent on `_raw.png`. Locked PNG gates exact nearest collapse only.

Wrong for this goal (keep as diagnostics only): soft radial influence
(`--influence-radius > 0`), Stage A as generative init, Infinity `gt_leak` from
Stage A VAE codes (dense soft-evidence continuation).

### Stage B (design B) — sparse lattice tokens → SD3.5 context

True-sparse conditioner: encode only NN lattice `(y,x,rgb)` into K Perceiver
tokens, concat onto SD3 `c_crossattn` before `context_embedder`. Empty latent.
No Stage A image as conditioner.

```bash
# Encoder-only train smoke (frozen SD3.5; V: weights)
"V:/ml/ComfyUI/.venv/Scripts/python.exe" \
  tools/local_imagegen/sparse_token_condition/train_smoke.py \
  --steps 30 --size 256 --scale 4 --num-latents 64 --embed-dim 256

# Infer + token ablation (with/without must diverge)
"V:/ml/ComfyUI/.venv/Scripts/python.exe" \
  tools/local_imagegen/sparse_token_condition/infer_smoke.py \
  --steps 12 --size 256 --scale 4 --seed 7
```

Weights: `V:/ml/models/sparse_lattice/smoke.pt`. Comfy node:
`comfy_custom_nodes/sparse_lattice_condition` (sync into
`V:/ml/ComfyUI/custom_nodes/`). Proven so far: train plumbing (non-zero encoder
grads) + infer ablation MAE divergence + locked exact collapse. CGI invent
quality unproven.

### Stage B alt — Infinity-2B (soft-evidence AR; not true sparse)

Infinity-2B on the 16GB card can teacher-force coarse scales from a Stage A encode
(`gt_leak`) then invent fine scales. That is collapse-compatible but **not** sparse
inpainting: VAE codes of Stage A are dense soft filler. Use only when deliberately
testing soft-evidence AR. FA + `empty_cache` before VAE decode: ~10–20s/image.

## Models currently on V:

| File | Purpose |
|------|---------|
| `models/checkpoints/v1-5-pruned-emaonly.safetensors` | SD1.5 base (Tile ControlNet lane) |
| `models/checkpoints/sd3.5_medium_incl_clips_t5xxlfp8scaled.safetensors` | SD3.5 Medium fp8 all-in-one (soft img2img lane) |
| `models/controlnet/control_v11f1e_sd15_tile.pth` | ControlNet Tile structure lock (SD1.5 only) |
| `models/upscale_models/RealESRGAN_x4plus.pth` | Classical upscaler baseline |
| `models/loras/retrocgi_sd15_v1.safetensors` | RetroCGI LoRA (SD1.5) |
| `models/infinity/infinity_2b_reg.pth` | Infinity-2B AR generator |
| `models/infinity/infinity_vae_d32reg.pth` | Infinity BitVAE d32 |
| `models/infinity/flan-t5-xl/` | T5 text encoder for Infinity |
| `models/sparse_lattice/smoke.pt` | SparseLatticeEncoder train-smoke weights (plumbing only) |

SD3.5 Medium is preferred over Large on the 16GB card. There is no mature SD3.5 Tile ControlNet in this install yet — use soft lanczos img2img for the 3.5 lane, and keep Tile on SD1.5.

## Exact-size CLI helper

```bash
bash tools/local_imagegen/comfyui_vdrive.sh serve

# Hobgoblin: soft diffusion + prompt + INTER-STEP nearest collapse
# 58x64 -> 928x1024 is 16x (integer; required)
# Restart Comfy after installing/updating the custom node.
python tools/local_imagegen/comfy_exact_img2img_sd35.py \
  --image artifacts/collapse_authentic_upscale/original/h3_hobgoblin.png \
  --out artifacts/collapse_authentic_upscale/candidates/hobgoblin_interstep.png \
  --width 928 --height 1024 \
  --denoise 0.45 --seed 7 \
  --interstep-nearest-collapse \
  --project-mode latent \
  --block-pull 0.45 \
  --denoise 0.60 \
  --positive "late 1990s pre-rendered 3D CGI hobgoblin portrait, Heroes of Might and Magic III, soft era CGI shading, not hand-painted, not photoreal"

python tools/local_imagegen/nearest_collapse.py --self-check
python tools/verify_upscale_collapse_authenticity.py \
  --original artifacts/collapse_authentic_upscale/original/h3_hobgoblin.png \
  --candidate artifacts/collapse_authentic_upscale/candidates/hobgoblin_interstep.png \
  --method nearest
```

`--width` / `--height` are required and must be multiples of 8 (SD1.5) or 16 (SD3.5), and
integer multiples of the source when using inter-step nearest collapse. The helper fails
if the saved PNG size differs.

### SD1.5 + Tile (optional structure lock)

```bash
python tools/local_imagegen/comfy_exact_img2img.py \
  --image artifacts/collapse_authentic_upscale/original/h3_hobgoblin.png \
  --out artifacts/collapse_authentic_upscale/candidates/hobgoblin_tile_nn.png \
  --width 928 --height 1024 \
  --controlnet-tile \
  --controlnet-strength 0.75 \
  --denoise 0.40 --seed 7 \
  --positive "late 1990s pre-rendered 3D CGI hobgoblin portrait, Heroes of Might and Magic III, soft era CGI shading"
```

SD1.5 helper still defaults to optional post sample-stamp; prefer moving that lane to the same inter-step node once validated on SD3.5.

## Proof status

- Install + CUDA device visibility: startup smoke proven (`torch 2.11.0+cu130`, RTX 5070 Ti).
- Exact-size SD1.5 / SD3.5 img2img helpers: source/static + local generation smoke.
- Nearest helpers (`nearest_collapse.py` self-check): source/static.
- Inter-step Comfy node + SD3.5 CLI wiring: source/static; runtime smoke when Comfy reloads the node.
- Hobgoblin kernel ID (nearest, not box): user visual from downsample lab / HI probes.
- F1 reward / DDPO LoRA overfit path: **removed** — superseded by inter-step nearest collapse.
- Sparse-token design B train/infer smoke: source/static + local plumbing proven
  (`smoke.pt`, ablation MAE); invent CGI unproven.
- Runtime “looks like 90s CGI” remains a human review call on generated candidates.
