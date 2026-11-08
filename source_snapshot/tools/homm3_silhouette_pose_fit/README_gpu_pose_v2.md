# HoMM3 GPU Pose Solver V2

V2 is a new pose-fitting lane beside the existing GPU-cascade notebook. The
legacy notebook is the comparison baseline and is not modified by this lane.

## Runtime contract

V2 requires all of the following:

- Python 3.12 with the existing CUDA-enabled PyTorch installation.
- A CUDA GPU. CPU and software-renderer fallbacks are intentionally rejected.
- The pinned NVLabs `nvdiffrast` CUDA extension and its Windows build tools.
- Authentic VCMI/HoMM3 DEF source frames. RIFE, interpolated, and upscaled
  target directories are rejected during preparation.
- Alpha-shadow culling through `def_soft_shadow.cull_def_soft_shadow_rgba`.
- A Meshy smart-rig GLB. Meshy remains the authoritative starting rig; V2
  constrains and evaluates it rather than replacing it.

The candidate loop never calls Blender, PIL, PNG output, or a compositor. Rest
geometry, skinning, projection, and filled triangle rasterization stay on
CUDA. Blender is used only for the final lit export and independent parity
report.

## Environment setup

Run this from the repository root in PowerShell:

```powershell
& .\tools\homm3_silhouette_pose_fit\setup_gpu_pose_v2.ps1
```

The script creates `.venv_gpu_pose_v2` on `V:`, exposes the existing CUDA
PyTorch installation through `--system-site-packages`, and installs the
commit-pinned nvdiffrast requirements. A Visual Studio C++ toolchain and
NVIDIA CUDA toolkit must already be installed. The notebook adds the local
`third_party\gpu_pose_v2` extension directory to `sys.path` when the locally
compiled extension is used.

The environment is deliberately not committed. Recreate it with the script
if its Python or CUDA toolchain changes.

## Notebook order

Open `homm3_gpu_pose_v2.ipynb` with the V2 kernel and run cells in order:

1. CUDA, VRAM, nvdiffrast, model-cache, and Blender preflight.
2. Unit, Meshy smart-rig, authentic DEF animation, and camera picker.
3. Explicit Meshy rigidization preparation and report inspection.
4. Preset and compact advanced overrides.
5. Immutable rig and clip preparation.
6. Static registration hypotheses, before articulation.
7. Whole-clip multi-hypothesis solve with one stable live dashboard.
8. Exact CUDA RGB/depth/alpha/IoU and front-upper-diagonal diagnostic preview.
9. Canonical artifact, Blender parity report, and 60 fps GIF/MP4 export.
10. Comparison against a frozen current-pipeline artifact when one is supplied.

The public Python surface is intentionally small. Session methods keep the
notebook from knowing about artifact paths:

```python
session = prepare_experiment(selection, preset, overrides)
result = solve_clip(session)
preview = session.preview(result)
result_path = session.export(result)
```

The notebook does not construct glTF transforms or invoke Blender worker
commands directly.

## DINOv3 dense features

The V2 notebook now follows the proven single-joint semantic setup by default:
global SigLIP2 remains the low-weight image-level signal, while
`facebook/dinov3-vits16-pretrain-lvd1689m` supplies the dense patch grid for
finalist comparison. The DINOv3 checkpoint is loaded through
`DenseFeatureScorer` on CUDA and is never silently replaced by SigLIP2.

The V2 preflight imports `HF_TOKEN` from the Windows user environment into the
current kernel when necessary, without printing or serializing the token. It
also reports whether the DINOv3 cache is present. Restart the kernel after
changing the user environment variable. The notebook's `V2_DENSE_ENCODER`
toggle selects either this DINOv3 path or the SigLIP2 dense ablation; its
`dense_model_family`, `dense_layers`, and `dense_local_files_only` values are
passed directly to the dense encoder. The notebook defaults to
`dense_local_files_only=True` so a run cannot unexpectedly block on a gated
Hub request after the checkpoint has already been downloaded.

## Generated front-view auxiliary evidence

When `front_view_enabled=True`, the picker maps each authentic DEF frame to
the corresponding generated front-perspective image under
`artifacts\sprite_profile_to_front\out`. These RGB-on-black images are not
treated as calibrated renders. Their foreground is extracted without using
render lighting, then each image is cropped, padded, centered, and normalized
to the configured `front_view_subject_extent`. After that per-image
normalization, V2 performs one shared bind-pose camera-scale fit
(`front_view_fit_camera_scale=True` by default) against the median normalized
extent. Candidate poses are scored in that fixed auxiliary camera, so a wrong
pose cannot improve its score by independently recentering or resizing itself.

The authentic profile silhouette remains the primary target. The auxiliary
front silhouette, edge/SDF field, and foreground-masked global/dense semantic
features supply secondary evidence for hidden-axis orientation and joint
ownership. The front-view provenance and fitted scale are written to
`v2_session.json` and the result artifact.

## Validation and proof boundary

Fast source/contract checks are available with:

```powershell
Push-Location tools\homm3_silhouette_pose_fit
python -m gpu_pose_v2.test_contracts
Pop-Location
python tools\homm3_silhouette_pose_fit\validate_gpu_pose_v2_contract.py path\to\gpu_pose_v2_result.json
```

`require_blender_parity(...)` is fail-closed at mean IoU `0.98`, minimum IoU
`0.95`, and centroid error below one optimizer pixel. The notebook leaves
parity enforcement off while the GPU-versus-Blender raster calibration is
being established per unit; it still writes and displays the report. Do not
promote an export to parity-proven until that gate passes.

V2 checkpoints include schema, rig/clip fingerprints, canonical pose tensors,
objective diagnostics, observability, and stage timing. The result validator
rejects missing source provenance, missing shadow culling, non-canonical pose
serialization, and non-nvdiffrast renderer claims.
