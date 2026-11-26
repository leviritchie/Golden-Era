# HoMM3 Full-PBR Retexturing (`tools/homm3_retexture_pbr/`)

Status: **Tooling & synthetic parity contract validated; Fortress (21 units) and Dungeon (`dungeon_rebuild_v1`, 21 units, native 2K Batches 2 & 4 + Batches 1 & 3) installed payload proven; runtime gameplay unproven.**

Generalized, faction-agnostic GPU multi-view retexturing + yaw-invariant Hex/Lit PBR baking pipeline promoted from the Fortress Basilisk/21-unit pilot and extended with direct native-`2K` Gemini API synthesis (`paint_api.py`).

## Owner Files
- Package: `tools/homm3_retexture_pbr/`
  - `def_sprite_loader.py` — reads canonical `artifacts/homm3_def_retarget/<unit>/<unit>_def_retarget.blend.frames.json` `sources` PNGs (filtering `alpha >= 200` to discard HoMM3 `64/128` ground shadows cleanly), with explicit `renders/cmp_*.png` fallback when `sources` are absent. Fails closed if neither exists.
  - `build_def_refs.py` — writes `<work-dir>/<unit>/ref/def_ref_2x2.png` (4 visually diverse crisp HoMM3 frames on neutral `#7F7F7F`).
  - `render_guides_unit.py` — evaluates `Unit_Idle` frame `0` in Blender 5.2.2 Cycles (`OPTIX`), **reverses inward faces (`svol < 0.0`) BEFORE baking 1024×1024 `uv_ao.npy` and rendering 8 calibrated ortho views + AOVs**, and frames multi-head units cleanly.
  - `paint_api.py` — calls `gemini-nano-banana-2.1` directly at native `2K` (`2048x2048`, `store=False`, omitted `mime_type` for PNG output), resolving live `HKCU\Environment` / `HKLM\...\Environment` `GEMINI_API_KEY` before stale process env vars, enforcing `save_and_check` IoU `>= 0.85` with one auto-correction retry, failing closed on `400/401/402/403/404/429`, and appending per-call usage/cost JSONL to `<work-dir>/renders/api_cost_log.jsonl`.
  - `save_and_check_sheet.py` — preserves native `2048x2048` generated sheets without resampling (LANCZOS-resizing non-2K inputs) and enforces panel foreground IoU `>= 0.85` against `<v>_alpha.npy`.
  - `project_unit.py` — deterministic CUDA UV rasterizer (`--device cpu` reference + `--parity-check`), `_fill_solid_interior_holes` (preserves enclosed `#7F7F7F` background gaps between tentacles/limbs while filling tiny interior paint specks), UV seam-sliver filter (`((uv_area > 0.0004) & (uv_area > 20.0 * med_ratio * area_3d)) | (e_uv > 0.14)`), multi-view linear brightness harmonization, fail-closed `cov >= 75.0%` & `ao_mean >= 0.30`, 24px CUDA gutter dilation, archetype-aware `metallicgloss.png` + `normal.png`, and yaw-invariant Full-PBR bake into `basecolor_hexlit_pbr.png` for Olden Era's diffuse-only `Hex/Lit` shader (`docs/homm3_prebaked_lighting.md`).
  - `render_batch_qa.py` & `compose_qa_board.py` — resolves work/rebuild/shipped paths for Blender and renders Olden Era diffuse `Hex/Lit`-matched Front/Rear/Head tiles alongside `HoMM3 DEF` and `Old Shipped` (or raw rebuild) tiles into labeled `batch_<N>_qa.png` boards.
  - `batch_driver.py` — single CLI entry (`prep`, `paint-api`, `check-sheet`, `project`, `qa-board`, `prune-temp`) enforcing `gpu_gate.py --slots 2 --min-vram 3200` on Blender stages.
- Skill: `.agents/skills/homm3-full-pbr-retexture/SKILL.md`
- Build validator: `tools/validate_homm3_retexture_pbr_contract.py` (`ValidateHomm3RetexturePbrContract` in `OfflineUnlockMod.csproj`, full-tier gated on `'$(FullValidationNormalized)' == 'true'`).

## Supersedes Legacy `look_run` for Rebuilt Units
Because `--retexture-dir <work-dir>` supplies `out/basecolor_hexlit_pbr.png` directly to `assemble_rebuild_slice.py`, rebuilt unit families skip legacy `look_sandbox` / `run_look` / `reel_look` / `compose_sbs`, eliminating redundant Cycles look fits and >20 GB per-unit scratch expansion.

## Validator Measurements
- `python tools/validate_homm3_retexture_pbr_contract.py` (2026-11-24):
  - Elapsed: `7.657s`
  - Peak Python traced RAM: `49.80 MiB`
  - Peak CUDA VRAM (64×64 synthetic parity fixture): `0.46 MiB`
  - Parity (`cpu` vs `cuda`): `posDiff=8.94e-08`, `nrmDiff=0.0`, `tanDiff=0.0`, `maskDiff=0`, `dilDiff=8.94e-08`, inverted-volume normal flip recovery `nrmFlipDiff=0.0`, enclosed hollow-ring IoU regression `ringHoleIoU=1.0`, offline `paintApiTested=True` (`generated artifact / source fixture validated`).
