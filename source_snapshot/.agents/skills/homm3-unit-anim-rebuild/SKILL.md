---
name: homm3-unit-anim-rebuild
description: >-
  Build or finish high-fidelity 30fps HoMM3 unit animations under
  V:/scratch_claude/unit_rebuild/ using starter templates, unified mechanical
  preflight gates, zero look_run, and cross-pool Claude + hydrogen-low QA routing.
---

# HoMM3 Unit Animation Rebuild Skill

Rebuilds Meshy creature animations in Blender 5.2.2 LTS (`V:/scratch_claude/unit_rebuild/<unit>/`)
for Olden Era delivery without legacy `look_run` (superseded by `homm3-full-pbr-retexture`).

## Model & Quota Routing
- **Routine archetype families (bipeds, quadrupeds, fliers, upgrade cloning):** `claude-sonnet-5-5-low` or `-medium` (**separate Claude quota pool — 0 Gemini spend**; if Claude returns `429 RESOURCE_EXHAUSTED`, fall back to `gemini-4-carbon-low` / `gemini-4-argon-low` / `gemini-4-neon-low`).
- **Exotic archetype founders (riders+mounts, centaurs, multi-limb) & severe Meshy surgery:** `claude-opus-5-5-medium` (escalate to `gemini-4-neon-low` / `-high` when Claude hits `429` or stalls).
- **Text-only math/config cloning overflow:** `gpt-oss-120b-medium` (never vision).
- **Unanchored visual QA ONLY:** Fresh **`gemini-4-hydrogen-low`** reviewer per family round (NEVER `flash`; NEVER Claude for unanchored QA). Kill every reviewer right after its verdict.

## Core Rules
1. **NO `look_run` / `look_sandbox` / `run_look` / `reel_look` / `compose_sbs`:** Texture look is handled downstream by `tools/homm3_retexture_pbr/` via `--retexture-dir`.
2. **Reuse `_templates/` first:** Start from `V:/scratch_claude/unit_rebuild/_templates/` (`biped_melee`, `biped_archer`, `quadruped`, `winged_flyer`, `serpent_flyer`, `multi_head`, `float_tentacle`, `serpent_archer`). Never reinvent bone hierarchies or clip math from scratch.
3. **Base-Then-Clone Family Protocol:** Build and pass the base tier unit cleanly (`preflight_gates.py` + `chk_vN/closeups.png` + review), then clone/adapt rig & clips to the upgrade tiers with staggered `#32` calm `Unit_Idle` frame counts (`114–162f`).
4. **Deterministic Gate BEFORE Vision Review:** Run `preflight_gates.py` and visually inspect a 20s `chk_vN/closeups.png` BEFORE spending a 4-minute full reel or calling `gemini-4-hydrogen-low`.

## Authoring Checklist
1. **Stage & Mesh Audit:** `prep.py` -> `src.blend`, `srcsheet.py` -> `src_sheet.png` (under `gpu_gate.py`). Sever any Meshy-fused limbs/weapons/wings cleanly before weighting (`0` unmapped groups, `0` empty-weight verts, crisp rigid weapon/prop weights).
2. **Densify & Bake:** `densify.py` -> `dense.blend`, `bake.py` (under `gpu_gate.py`) -> `baked.blend` + `tex/{basecolor,metallic,roughness,normal}.png`.
3. **Clips & Non-Negotiable Constraints:**
   - All base DEF clips (`Unit_Idle`, `Unit_MoveStart`, `Unit_Move`, `Unit_MoveEnd`, `Unit_AttackFront`, `Unit_Hitted`, `Unit_Defence`, `Unit_Mouseover`, `Unit_Death`, plus `Unit_ShootFront` / specials if present in `base_look_glb` / `frames.json`).
   - **Melee `Unit_AttackFront` whip-swing standard:** Follow [docs/homm3_melee_attack_whip_methodology.md](../../docs/homm3_melee_attack_whip_methodology.md) (`V:/scratch_claude/unit_rebuild/h3_gnoll/clips.py` reference: `dur ~ 1.33–1.60s`, vanilla-matched `dCOM ~ +0.25–0.40 H`, set `SMOOTH_F['Unit_AttackFront'] = 7.0–7.5` because omitting it defaults to `3.0 Hz` in `_lib/biped.py`, held anticipation clear of snout -> `3–4f` whip arc -> `2f` hitstop -> follow-through -> weighted step-back).
   - `#31` distinct creature behavior in `Unit_Idle` + `#32` calm native cadence (`114–162f` at 30fps, `angMed 5–14 deg/s`, `pkMed 10–30 deg/s`, `maxNonWingBonePeak <= 115 deg/s`, Wiggle 2 damped/off in idle).
   - Frame-0 grounding: put `Unit_MoveStart`, `Unit_MoveEnd`, `Unit_Defence`, `Unit_Death` in `NO_GROUND`, keep `f=0 == I0`, and flatten `Death` pose onto `z >= 0`.
4. **Unified Mechanical Preflight Gate (mandatory):**
   ```powershell
   python tools/homm3_unit_anim_rebuild/preflight_gates.py `
     --unit <unit> `
     --base-selection tools/homm3_def_retarget_delivery/<faction>_slice_v1.json
   ```
   Requires `PASS` across `files`, `stride`, `calm_idle`, `smoke_gates`, and `anim_qc` (`vib=0`, `below=0`, `seam <= 0.005`).
5. **Fast Closeups -> Full Reel -> Unanchored `gemini-4-hydrogen-low` Review:**
   - Render `chk_vN/closeups.png` (under `gpu_gate.py`), fix obvious clipping/backward-weapon/floating bugs immediately.
   - Render full `reel_vN` + `sheets/` + `closeups.png` (`gpu_gate.py --slots 2 --min-vram 3200`).
   - Spawn ONE fresh `gemini-4-hydrogen-low` reviewer per 3-unit family inspecting ONLY `closeups.png` + `sheets/Unit_*.png` (unanchored prompt — zero mention of QC numbers or prior rounds). Stop as soon as `0 FAIL` (and all major issues cleared).
6. **Disk Hygiene (`deliver/` & Prune):** Keep `out/<unit>.glb`, `tex/`, `qc/`, `deliver/{sheets/*.png,*_closeups.png}`, `.py`, `.json`. Delete raw `reel_v*/frame_*.png`, `chk_v*`, `src.blend`, `dense.blend`, `src_unprebaked.glb`, `W0.npy`, and any old `look_run/` scratch.
