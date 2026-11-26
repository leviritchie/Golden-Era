# HoMM3 Melee Whip-Swing Attack & Cross-Faction Pipeline Handoff

Operational methodology, technical pitfalls, and live cross-faction tracker for:
1. Retrofitting existing rebuilt melee units with vanilla-matched deep lunge + stylized whip-swing `Unit_AttackFront` animations (modeled after the approved `h3_gnoll` prototype).
2. Advancing remaining factions through 30fps animation rebuilds (`homm3-unit-anim-rebuild`) and decoupling 2K `gemini-nano-banana-2.1` Full-PBR retexturing (`homm3-full-pbr-retexture`) so texture synthesis runs in advance without waiting unit-by-unit on animation rebuilds.

---

## 1. Vanilla Olden Era Melee Benchmark (`N = 17` Units)

Measured directly on `resources.assets` (`_Battle_Unit_Anim_ctrl_v2`: `14.Attack` vs `22.Idle`) along battle-forward `+X` at exact `UnitViewConfig.scale` (checked across `52` vanilla melee controllers: `root_fwd = 0.000` on all of them — Olden Era melee units keep `Root` stationary and drive lunge reach via `Hips` translation + footwork):

| Metric | Vanilla Median / Range | Legacy `h3_gnoll` (8f DEF) | Approved `h3_gnoll` Whip (`be5855dbe9`) |
|---|---|---|---|
| Attack clip duration | `1.47 s` (`p25–p75: 1.33–2.17 s`) | `0.967 s` (`30f`) | `1.433 s` (`44f @ 30 fps`) |
| Hip forward travel (`dHips`) | `+0.34 m` (`0.12–0.24 H`) | `+0.17 m` (`0.10 H`) | `+0.56 m` (`0.33 H`) |
| Skinned COM surge (`dCOM`) | `+0.66 m` (`0.28 H`, `p25–p75: 0.23–0.36 H`) | `+0.26 m` (`0.15 H`) | `+0.68 m` (`0.39 H`) |
| Peak attack reach (`atkZ` / `atkX`) | `+2.10 m` (`0.96–1.18 H`) | `+1.60 m` (`0.93 H`) | `+2.17 m` (`1.26 H`) |
| Reach past attack-frame COM | `0.77 H` | — | `0.83 H` |

**Core design lesson:** Previous rebuild `Unit_AttackFront` clips kept feet/hips near home hex (`dCOM <= 0.15 H`) and suffered from excessive low-pass smoothing (`2.8–3.0 Hz`), making attacks look like static arm shoves short of the target hex.

---

## 2. Stylized Whip-Swing Methodology (`h3_gnoll` Reference)

Reference implementation: `V:/scratch_claude/unit_rebuild/h3_gnoll/clips.py` (deployed at commit `be5855dbe9`).

### A. Non-Smearing `SMOOTH_F` & Spring Limits
- **`_lib/biped.py:163` trap:** `author_all()` runs `smoothed(fn, n, f=(smooth_f or {}).get(name, 3.0))` on **every** non-loop clip. Omitting `'Unit_AttackFront'` from `SMOOTH_F` does **not** disable smoothing — it silently falls back to `3.0 Hz`, which crushes a 3–4 frame whip (`[-80°, +96°]` gets damped to `[-37.5°, +43.4°]`).
- **`tools/asset_mcp/blender/unit_anim_physics.py` `SecondOrder.step` trap:** At 30 fps (`dt = 1/30`), passing `f <= 0`/`None` divides by zero, while `f >= 10–12 Hz` hits the `k2` stability clamp and causes underdamped ringing (`[-80° -> -105.4° -> +134.5°]`).
- **Standard:** Explicitly set `'Unit_AttackFront': 7.5` (or `7.0–7.5`) in `SMOOTH_F` for biped melee attackers (`[ -79.6, -79.4, -51.1, +20.1, +94.6, +94.9 ]` — preserves ~98% whip amplitude while rounding sharp corners enough to keep `vib=0`). Use equivalent high-cutoff/crisp timing on quadruped, flyer, dragon, and multi-head clips.

### B. Asymmetric Stylized Rhythm & Silhouette
1. **Coil & Moving-Hold Anticipation (`f4`–`f11`):**
   - Step mass backward (`ty > 0`), lift front foot slightly, rotate chest away (`sy ~ +48°..+52°`), cock weapon arm **back-and-wide** behind shoulder (`afL ~ -20°..-24°`, `aaL ~ +82°..+84°` for Gnoll-like forehand cleave) so haft/chain/weapon sits clearly above/behind the mane/snout with zero facial intersection. Hold with slight creep (`f7` → `f11`) rather than freezing dead.
2. **Explosive 3–4 Frame Whip Launch (`f11` → `f15`):**
   - Lead with hips + front foot surge (`f12`), sweep shoulder/torso open wide (`f13`), slam front foot deep (`fwdL = +0.60..+0.62`, rear foot stepping forward `fwdR = +0.12..+0.14` so `soft_ik` never tethers hips back) (`f14`), and crack the weapon diagonally forward-across (`f15`, `tPeak ~ 0.50–0.57 s`).
   - **Never point a handle/haft collinearly along the arm:** keep wrist/twist offset (`wyL`, `atL`) perpendicular/angled across the strike arc (`"cracking the whip"`) rather than a straight spear-poke.
   - Keep shoulder/chest/limb/weapon angles monotone through the snap (`f11` → `f15`) so `DEF-*` joints do not S-curve or oscillate in X/Y/Z (`vib = 0`).
3. **Hard 2-Frame Hitstop (`f15`–`f17`):**
   - Hold full lunge extension with subtle weight drop (`tz` slightly lower, slight chain/tip flex through) so impact registers heavily.
4. **Decisive Follow-Through (`f19`–`f22`):**
   - Cleave diagonally down-and-across front (clear above thighs/knees) instead of pulling straight backward.
   - **Floor-clamp boundary trap (`_GnollPoser`):** When a solver blends toward horizontal near `z_floor + margin`, lowering a dangling flail across that height threshold during `f22`–`f28` induces a 1-frame lateral snap (`vib > 0`). Keep `fl_floor` safely low (`0.04`) on follow-through/recovery and hold the forearm slightly higher until clear.
5. **Weighted Step-Back Recovery (`f26`–`f43`):**
   - Push rear foot back first (`f31`), then lift and plant front foot back to `I0` (`f37` → `f43`), with monotone weapon settle. Keep `WIGGLE=0` during `export.py` whenever `clips.py` drives chains/props directly.

### C. Reconstructing `weighted.blend` on Pruned Units Without Rebaking Full-PBR UVs
Most shipped units in `V:/scratch_claude/unit_rebuild/<unit>/` had `weighted.blend`, `anim.blend`, `game.blend`, and `tex/{normal,metallic,roughness}.png` deleted to preserve disk space (`V:` ~20 GB free). **Never re-run `densify.py` or `bake.py`** on an already Full-PBR-retextured unit (rebaking shifts UVs/weights and misaligns `basecolor_hexlit_pbr.png`). Instead:
1. Model reconstruction after `V:/olden_port_work/gnoll_lunge_proto/rebuild_gnoll_weighted.py`:
   - Import the unit's existing `artifacts/homm3_def_retarget_delivery/<faction>_rebuild_v1/<unit>/inputs/look_delivered.glb` (or `out/<unit>.glb`) to preserve exact vertex count, vertex order, UVs, and `DEF-*` vertex groups (`0` empty weights).
   - Rebuild the exact control armature from the unit's `bones.json` and rig builder (`rig_*.py` or `_lib/rig_*.py`), save `weighted.blend`.
2. If `tex/{normal,metallic,roughness}.png` were pruned, extract them from the GLB (`metallic-roughness` image: G channel → `roughness.png`, B channel → `metallic.png`; `normal` → `normal.png`). Preserve `tex/basecolor.png` as-is during export.
3. Run Blender 5.2.2 LTS (`V:/Tools/blender-mcp/blender-5.2.2/blender.exe --background --python-exit-code 1`) with `$env:NOPV='1'` (`animate.py`) and `$env:WIGGLE='0'` (`export.py` when clip-driven). Note PowerShell 5.1 syntax (`; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }`, `@' ... '@ | python -`).
4. Run unified mechanical preflight:
   ```powershell
   python tools/homm3_unit_anim_rebuild/preflight_gates.py `
     --unit <unit> `
     --base-selection tools/homm3_def_retarget_delivery/<faction>_slice_v1.json
   ```
   Must report `PASS` (`files`, `stride`, `calm_idle`, `smoke_gates`, `anim_qc`: `vib=0, below=0, seam<=0.005`).
5. Measure reach (`V:/olden_port_work/gnoll_lunge_proto/measure_gnoll.py` pattern) and render + `read_file`-inspect a 30fps preview (`sc.render.fps = 30` *before* `bpy.ops.import_scene.gltf`, using Full-PBR `basecolor.png` for texture clarity).
6. **Disk Hygiene (`V:` >= 20 GB free):** Immediately remove temporary `weighted.blend`, `anim.blend`, `game.blend`, `*.blend1`, raw render frames, and extracted `tex/{normal,metallic,roughness}.png` once each unit passes.

---

## 3. Delivery & `Core.zip` Timing Sync Workflow (Coordinator Only)

Workers **must not** invoke Unity, deploy bundles, edit `Core.zip`, or run `git`. Coordinator executes per completed faction batch:
1. **Assemble updated unit(s) into `*_rebuild_v1` while preserving Full-PBR textures:**
   ```powershell
   python V:/scratch_claude/unit_rebuild/_fortress_coord/assemble_rebuild_slice.py `
     --base-selection tools/homm3_def_retarget_delivery/<faction>_slice_v1.json `
     --out-selection V:/olden_port_work/<tmp>_assembled.json `
     --units u1,u2,... `
     --retexture-dir <retexture_root> `
     --slice <faction>_rebuild_v1 `
     --out-dir artifacts/homm3_def_retarget_delivery/<faction>_rebuild_v1 `
     --smoke-check
   ```
   Then splice with `python tools/homm3_def_retarget_delivery/splice_rebuild_rows.py --assembled <tmp>_assembled.json --target tools/homm3_def_retarget_delivery/<faction>_rebuild_v1.json --retexture-dir <retexture_root> [--units ...] [--attack-hits <json {labSid: tPeak}>]` (run `--dry-run` first). It replaces only the given rows, keeps each row's existing `attackTiming` unless `<rebuild-root>/<unit>/rebuild_report.json` or `--attack-hits` gives a fresh one, and aborts if a `basecolorSha256` is neither unchanged, the graded sha (`out/graded/grade.json` `installedSha256`), nor a new unit. Fortress retexture dir: `V:/olden_port_work/retexture_exp/fortress`; Dungeon retexture dir: `V:/olden_port_work/retexture_pbr/dungeon`.
2. **Ship via Unity Queue:**
   ```powershell
   foreach ($st in @('prepare', 'lab', 'bundles', 'probe', 'deploy')) {
     python tools/homm3_def_retarget_slice.py $st ...
   }
   ```
   (Specifically `tools/homm3_def_retarget_delivery/ship_def_retarget_slice.py $st --selection tools/homm3_def_retarget_delivery/<faction>_rebuild_v1.json`.)
3. **Sync `Core.zip` attack contact timings:**
   - The timing table now includes rebuild slices (fixed 2026-11-25): `attack_timing.py` and `validate_homm3_attack_timing.py` read `*_slice_v1.json` **and** `*_rebuild_v1.json` (rebuild rows win). Record each re-authored attacker's measured impact in its rebuild row:
     `"attackTiming": {"Unit_AttackFront": {"hit": <tPeak seconds>, "source": "..."}}` (and `Unit_ShootFront` for shooters). Rows without it get the DEF climax/reach frame scaled onto the new clip length.
   - Then `python tools/homm3_def_retarget_delivery/attack_timing.py build --only <gameSids comma-separated>` and `python tools/homm3_def_retarget_delivery/sync_core_attack_timing.py --core <Core.zip> --units <gameSids> --backup-dir V:/olden_port_work/<dir>` (uses the release overlay's `assign_homm3_attack_timings`, rewrites only those `_v.json` entries, verifies every other entry byte-for-byte, backs up `Core.before_timing_<sha8>.zip`). Never hand-edit the view JSON: the next release overlay rewrites `attackTimeBefore/After` from the table. Then `python tools/validate_homm3_attack_timing.py --core <Core.zip>` must pass.
   - **The table pins each unit's GLB sha.** Any re-assembly, including a texture-only regrade redeploy, needs `attack_timing.py build --only <those gameSids>` even when the timings did not change, or the validator reports a sha mismatch.
4. **Required post-deploy gates:**
   - `python tools/validate_homm3_def_retarget_delivery_contract.py --selection <faction>_rebuild_v1.json --require-installed`
   - `python tools/validate_homm3_unit_view_helper_contract.py --require-artifacts`
   - `python tools/validate_plugin_payload_abi_contract.py`
   - `python tools/validate_homm3_owned_skinned_attack_clip_contract.py --bundle-dir "<GE install>/BepInEx/plugins/OfflineUnlockMod/homm3_bundles" --name-prefix custom_units_<faction>_<unit> --core ".../Core.zip"`
   - Update `docs/ingame_check_queue.md` and commit only scoped manifest/docs changes.

---

## 4. Advance 2K Nano Banana 2.1 Pre-Painting Workflow

Because texture synthesis runs via direct `GEMINI_API_KEY` calls (`tools/homm3_retexture_pbr/paint_api.py`, `gemini-nano-banana-2.1` @ `2K`) and **does not wait on animation rigging**:
- Use `--source-slice-root artifacts/homm3_def_retarget_delivery/<faction>_slice_v1` in `batch_driver.py prep` and `batch_driver.py qa-board` to generate guides, paint 2K `repaint_primary.png` / `repaint_secondary.png` (`paint-api`, IoU >= 0.85), run CUDA `project`, render QA boards, inspect, and run `prune-temp` ahead of animation rebuilds.
- `_select_body_mesh()` in `tools/homm3_retexture_pbr/{render_guides_unit.py,render_batch_qa.py}` ignores secondary `*_Rubble` death-effect meshes (`not o.name.lower().endswith("_rubble")`) so legacy `look_delivered.glb` exports select the primary character mesh cleanly.
- **HoMM3 tone grade (owner-approved 2026-11-25), after every `project`:** `python tools/homm3_retexture_pbr/color_grade.py --work-dir <dir> --units <list> --install` matches each unit's brightness / contrast / saturation / hue to its own DEF frames, then judge QA boards from the graded textures. HoMM3 sprites carry harsh pre-baked key light, self-shadow and dark rims; that is lighting, not texture (Olden Era lights the mesh itself), so only the **lit half** of each image is compared (brightness at L p75, contrast as the lit-half spread only, chroma/hue of lit pixels), the DEF target is the median of per-frame stats (drops effect frames), and every factor is clamped. `--install` keeps `out/pre_grade/` originals and is idempotent (sha recorded in `out/graded/grade.json`). Rollout log: `V:/olden_port_work/retexture_pbr/grade_rollout_20261125.log`. A global grade cannot fix paint identity (e.g. Castle `h3_cavalier` horse painted chestnut; HoMM3 horse is tan) — those need a repaint.
- **Reusability guarantee:** `batch_driver.py prune-temp` preserves `out/repaint_primary.png`, `out/repaint_secondary.png`, `ref/def_ref_2x2.png`, and QA sheets while reclaiming multi-GB `.npy`/`.npz` intermediates. When a faction's animation rebuild later produces final `V:/scratch_claude/unit_rebuild/<unit>/out/<unit>.glb` (even if `densify.py` smooths interior UV coordinates), re-running `batch_driver.py prep` (default `rebuild-root`) + CUDA `project` re-bakes `basecolor_hexlit_pbr.png` onto the exact rebuild UVs in **~1.5 s/unit on CUDA with zero extra Gemini/Nano Banana 2.1 calls** (`paint-api` skipped cleanly!).

---

## 5. Live Faction & Unit Pipeline Status Tracker

*Update this table as batches finish so any agent can resume cleanly without redoing completed work.*

| Faction | Slice / Selection | Units | Anim Rebuild + Calm Idle | Stylized Melee Whip Pass | 2K Full-PBR Retexture (`work-dir`) | Installed / `Core.zip` State |
|---|---|---|---|---|---|---|
| **Fortress** | `fortress_rebuild_v1.json` (21) | `h3_gnoll`, 17 melee, 3 ranged (`lizardman*`) | Done (21/21) | **`18/18` melee DONE (`h3_gnoll` `be5855dbe9` + 17 retro `0a7993c7ef`)** | Done + HoMM3 tone grade (`V:/olden_port_work/retexture_exp/fortress`) | **Graded redeploy 2026-11-25 09:07 (`Core.zip` `5310c846` after lizardman timing sync, 4/4 validators PASS; runtime gameplay unproven)** |
| **Dungeon** | `dungeon_rebuild_v1.json` (21) | 15 melee, 6 ranged (`beholder*`, `medusa*`) | Done (21/21) | **`15/15` melee DONE (Claude takeover 2026-11-25):** all pass `preflight_gates`; dragons got a wing-weight repair, manticore/scorpicore/chimera a monotone tail whip; tPeak hits in `V:/olden_port_work/redeploy_20261125/dungeon_tpeak.json` | Done + HoMM3 tone grade (`V:/olden_port_work/retexture_pbr/dungeon`) | **Installed 2026-11-25 10:53 (`Core.zip` `e4eb68db`, timing validator 0 errors, 4/4 gates PASS; runtime unproven)** |
| **Necropolis** | `necropolis_slice_v1.json` (21) | Skeleton/Zombie/Vampire/Wight/Lich/Knight/Dragon | **`21/21` `preflight_gates` PASS** (`necro-anim-bipeds` 9, `cavalry` 3, `casters-r2` 9). **3 visual fixes before assembly:** `h3_bone_dragon` (Check all Dragons: detached left-wing shoulder/claw in `deliver/h3_bone_dragon_closeups.png`), `h3_lich` (Check all Liches: `Unit_Death` robe/staff stretch to boot in `deliver/h3_lich_closeups.png`), `h3_skeleton_archer` (thin Meshy skirt-to-bow-tip bridge `x<=0.23` stretches slightly in `Unit_ShootFront`) | Baked into rebuild (`SMOOTH_F >= 6.8` whip-swing + staggered `#32` calm idles) | **Advance 2K Done** (`V:/olden_port_work/retexture_pbr/necropolis`, `42/42` sheets, `$2.7032`; `17/21` projected on legacy GLBs, `4/21` `<75%` cov saved 2K sheets -> re-run zero-API `batch_driver.py prep` + CUDA `project` across all 21 rebuilt GLBs after visual fixes!) | Legacy `necropolis_slice_v1` installed |
| **Castle** | `castle_slice_v1.json` (18) + `castle_griffin_slice_v1.json` (3) | 21 units | In progress 2026-11-25 (Claude family workers, brief `V:/scratch_claude/unit_rebuild/_fortress_coord/CLAUDE_FAMILY_BRIEF.md`): pikeman, swordsman, cavalier, archer families; monk, angel, griffin next | To be baked in during rebuild | **Advance 2K Done** (`V:/olden_port_work/retexture_pbr/castle`, `42/42` sheets, `$3.5232`; `20/21` projected, `h3_guardsman` `71.68%` legacy cape awaiting rebuilt GLB; `h3_archangel` shield plate dark patch to re-project after rebuild) | Legacy `slice_v1` installed |
| **Rampart** | `rampart_slice_v1.json` (18) + `pegasus_slice_v1.json` (3) | 21 units | Queued | To be baked in during rebuild | **Advance 2K Done** (`V:/olden_port_work/retexture_pbr/rampart`, `42/42` sheets, `$2.8325`; `20/21` projected + visually verified smooth 2K after `h3_dwarf_battlerager` anti-pixel-art regen `85.30%`; `h3_pegasus` `74.96%` legacy wing/rider occlusion saved 2K sheets `IoU>=0.883` for post-rebuild zero-API CUDA projection) | Legacy `slice_v1` installed |
| **Tower** | `tower_slice_v1.json` (21) | 21 units | Queued | Pending | Queued (next advance 2K PBR candidate!) | Legacy `slice_v1` installed |
| **Inferno** | `inferno_slice_v1.json` (20) + `inferno_hell_hound_slice_v1.json` (1) | 21 units | Queued | Pending | **Advance 2K Done + graded** (`V:/olden_port_work/retexture_pbr/inferno`, 21/21 painted, `$3.236`; 20/21 projected 81-95%; `h3_efreeti` 57% legacy vortex occlusion -> re-project on rebuilt GLB; repaints magog/gog/arch_demon) | Legacy `slice_v1` installed |
| **Stronghold** | `stronghold_slice_v1.json` (19) + `boar_rider`/`orc` | 21 units | Queued | Pending | **Advance 2K Done + graded** (`V:/olden_port_work/retexture_pbr/stronghold`, 21/21 painted+projected 81-95%, `$2.724`; roc repainted tan head; `toa_boar_rider` DEF via `h3_boar_rider` alias in `def_sprite_loader.py`) | Legacy `slice_v1` installed |
| **Cove** | `cove_slice_v1.json` (21) | 21 units | Queued | Pending | Queued | Legacy `slice_v1` installed |
| **Factory** | `factory_slice_v1.json` (23) + `factory_mechanic_slice_v1.json` (1) | 24 units | Queued | Pending | Queued | Legacy `slice_v1` installed |
| **Conflux** | `conflux_slice_v1.json` (19) + `conflux_vanilla_style_slice_v1.json` (2) | 21 units | Queued | Pending | Queued | Legacy `slice_v1` installed |
| **Bulwark** | `bulwark_slice_v1.json` (17) + `bulwark_upg_alt_slice_v1.json` (5) | 22 units | `hota_bulwark_great_shaman` WIP | Pending | Queued | Legacy `slice_v1` installed |

### Handoff Checklist for Next Session / Coding Agent
1. Check `git --no-pager log -n 10 --oneline` and `V:/olden_port_work/` (`retexture_pbr/`, `retexture_exp/`, `melee_whip_retro/`). Current `V:` free space at handoff: `~40.8 GiB` (after `clip_pass` + `moge_rollout` + `kokon/KokonData/sdcpp/models` cold offloads).
2. Inspect `api_cost_log.jsonl` inside each `V:/olden_port_work/retexture_pbr/<faction>/renders/` (`necropolis` `$2.7032`, `castle` `$3.5232`, `rampart` `$2.8325`) and advance remaining factions (`Tower` -> `Inferno` -> `Stronghold` -> `Cove` -> `Factory` -> `Conflux` -> `Bulwark`) via `batch_driver.py` (`paint_api.py` now enforces the anti-pixel-art style guardrail at `7d0c5e9da6`; still inspect every `batch_*_qa.png` via `read_file`).
3. **Next immediate anim/delivery steps:**
   - **Dungeon melee whip retro:** done (15/15); deploy state is in the tracker above and `docs/ingame_check_queue.md`.
   - **Necropolis rebuild (`21/21` `preflight_gates` done):** fix the 3 visual defects above (`h3_bone_dragon` wing, `h3_lich` death robe/boot stretch, `h3_skeleton_archer` skirt-bow bridge), then re-run `batch_driver.py prep` + CUDA `project` across all 21 rebuilt `out/<unit>.glb` files (zero API cost using saved `V:/olden_port_work/retexture_pbr/necropolis/*/out/repaint_*.png`) -> `assemble_rebuild_slice.py` -> `necropolis_rebuild_v1.json` -> Unity deploy + `Core.zip` timings.
4. For any Fortress/Dungeon units whose `V:/scratch_claude/unit_rebuild/<unit>/clips.py` has `'Unit_AttackFront': 7.5` (or crisp non-3Hz whip curves) and a passing `preflight_gates.py` run newer than the slice selection JSON, run Section 3 (`assemble_rebuild_slice.py --units ...` -> splice into `*_rebuild_v1.json` -> `ship_def_retarget_slice.py` -> sync `Core.zip` timings -> 4 validators).
5. **Never revert or stage unrelated WIP** in `OfflineUnlockMod/` (`26640613` port edits) or town scenes when committing delivery manifests/docs.
6. **Antigravity worker routing:** Default Antigravity swarm/subagent workers to the Gemini pool (`gemini-4-neon-*` for complex coding/rigging, `gemini-4-hydrogen-*` for cost-efficient scripted pipelines/QA); reserve third-party models for select circumstances only.
