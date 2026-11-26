---
name: homm3-full-pbr-retexture
description: >-
  Run the crystallized, low-Gemini multi-view Full-PBR Hex/Lit retexture pipeline
  for HoMM3 rebuilt meshes (`tools/homm3_retexture_pbr/`). Use for any faction
  batch after animation GLBs pass `preflight_gates.py`.
---

# HoMM3 Full-PBR Retexture Batch Workflow

Turns rebuilt Meshy animation GLBs (`V:/scratch_claude/unit_rebuild/<unit>/out/<unit>.glb`)
into HoMM3-DEF-authentic textures (`basecolor_hexlit_pbr.png` baked for Olden Era's diffuse-only
`Hex/Lit` shader, plus `basecolor_albedo.png`, `normal.png`, `metallicgloss.png`).

## Quota & Model Routing Rules
1. **Batch driver / coordinator:** Run on `claude-sonnet-5-5-low` (or `-medium`) — **0 Gemini LLM burn** (if Claude returns `429 RESOURCE_EXHAUSTED`, fall back to `Model="flash"` `self` subagents or `gemini-4-carbon-low`).
2. **Texture synthesis (default — native 2K Direct API):** Use `tools/homm3_retexture_pbr/paint_api.py` (`python tools/homm3_retexture_pbr/batch_driver.py paint-api ...`, model `gemini-nano-banana-2.1` @ `image_size="2K"`, resolving live Windows `HKCU\Environment` `GEMINI_API_KEY` before stale process env and logging spend to `<work-dir>/renders/api_cost_log.jsonl`). Works directly from any worker/shell with zero `image-generator` subagent overhead.
   - *`$0` Ultra alternative:* Launch parent `invoke_subagent(TypeName="self", Model="flash", ...)` drivers calling `invoke_subagent(TypeName="image-generator", ...)` (note: swarm workers do **not** have `invoke_subagent` and `gemini-3.1-flash-image` caps near ~100 sheets per 5h rolling window).
3. **Unanchored batch QA reviewer:** Spawn ONE fresh **`gemini-4-hydrogen-low`** swarm helper per 4–6 unit batch inspecting **ONLY** `<work-dir>/renders/batch_<N>_qa.png`.
   - NEVER use `flash` or high-tier Neon/Opus for routine batch QA.
   - Kill every batch QA helper immediately after receiving its PASS/FAIL verdict.
   - NEVER post `@all` on any swarm board.

## Canonical Archetypes (`--units unit:archetype`)
Choose per unit after inspecting `batch_<N>_prep_sheet.png`:
- `generic_creature` — default organic skin/hide/fur (`rel_z < 0.18` matte feet `0.12`, satin `0.24`, uses `tex/metallic.png` if present)
- `reptile_green` — green/emerald scaled reptiles (`basilisk`, `dragon`, `serpent`, etc.; deep emerald contrast + matte feet `0.11`)
- `armored_metal` — heavy steel/brass/bronze armor or weapons (`gnoll`, `gorgon`, `minotaur`, `medusa_warrior`, `black_dragon`, knights; metallic `0.78–0.85` on steel/gold)
- `chitin_insect` — glossy carapace / multi-eye / winged insects (`flies`, `beholder`, `evil_eye`, `fargazer`, `scorpio`; chitin `0.44`, highlights `0.58`)
- `leather_cloth` — leather harnesses, cloaks, winged hides, bows (`lizardmen`, `wyverns`, `hydras`, `medusa_queen`, `fury`, `red_dragon`; matte feet `0.12`, satin `0.24`)
- `bone_stone` — skeletons, bone dragons, gargoyles, golems (`0.16` matte dry stone/bone, metallic trim via `tex/metallic.png`)
- `ethereal_glow` — ghosts, elementals, genies, efreeti, shadow dragons (`0.42–0.58` satin sheen, `0.86` luminous eyes)

---

## 5-Step Batch Execution

Let `WORK_DIR=V:/olden_port_work/retexture_pbr/<faction>` and `SHIPPED_ROOT=V:/Games/Olden Era Playtest Tweak/artifacts/homm3_def_retarget_delivery/<faction>_slice_v1` (omit `--shipped-root` if no prior slice exists).

### Step 1: Prep & Inspect Batch Contact Sheet
```powershell
python tools/homm3_retexture_pbr/batch_driver.py prep `
  --work-dir $WORK_DIR `
  --units u1,u2,u3,u4,u5 `
  --batch-out $WORK_DIR/renders/batch_<N>_prep_sheet.png
```
When pre-painting a faction **in advance** of animation rebuilds (whose `out/<unit>.glb` does not exist yet under `V:/scratch_claude/unit_rebuild/`), pass `--source-slice-root artifacts/homm3_def_retarget_delivery/<faction>_slice_v1` to both `prep` and `qa-board` (`inputs/look_delivered.glb` + `inputs/basecolor.png`; fails closed if missing). See [docs/homm3_melee_attack_whip_methodology.md](../../docs/homm3_melee_attack_whip_methodology.md) Section 4 (`repaint_*.png` survive `prune-temp` and re-project onto future rebuild GLBs in ~1.5s/unit on CUDA with zero extra API calls).
Read **ONLY** `$WORK_DIR/renders/batch_<N>_prep_sheet.png` via `read_file` (one image per 5-unit batch!).
Record for each unit:
- Exact HoMM3 DEF palette zones (primary hide/scale color, belly/chest color, eyes, teeth/horns/claws, armor/weapons, wings/spikes).
- Refine archetype if needed from `generic_creature` -> `armored_metal` / `chitin_insect` / etc.
- Note any `[flipped normals]` tag (already fixed automatically by `render_guides_unit.py` BEFORE AO baking!).

### Step 2: Generate Sheet 1 (`primary`) + Fail-Closed IoU Gate
Author `<work-dir>/renders/batch_<N>_prompts.json` (`{ "<unit>": { "primary": "...", "secondary": "..." } }`) matching the locked Sheet 1 & Sheet 2 templates below, then paint at native `2K` directly (passing Guide Image 1 + DEF Image 2 automatically, checking panel alpha IoU `>= 0.85` with enclosed-background-hole protection, retrying once on IoU drift, and logging exact spend to `api_cost_log.jsonl`):
```powershell
python -u tools/homm3_retexture_pbr/batch_driver.py paint-api `
  --work-dir $WORK_DIR --manifest $WORK_DIR/renders/batch_<N>_prompts.json --sheet primary --jobs 4
```
- **Locked Sheet 1 Prompt Template:**
  > Repaint Image 1 (`guide_sheet_primary.png` — 2x2 orthographic views of `<unit>`: Top-Left = Right Profile, Top-Right = Left Profile, Bottom-Left = Front View, Bottom-Right = Top Overhead View) in rich, hand-painted HoMM3 tactical-RPG miniature style using the exact colors, markings, eyes, and material cues from Image 2 (`def_ref_2x2.png`).
  > CREATURE PALETTE & MATERIALS: `<1–2 sentence exact palette description per body zone from prep sheet>`.
  > STRICT LAYOUT LOCK: Keep every pixel silhouette, limb position, pose, scale, and the solid neutral mid-gray `#7F7F7F` background completely unchanged inside all 4 panels. Zero text, borders, or pose shifts. Soft uniform neutral studio diffuse lighting with clean micro-detail (no harsh directional shadows or colored rim light).

### Step 3: Generate Sheet 2 (`secondary`) Locked to Sheet 1 + IoU Gate
Run `paint-api --sheet secondary` (automatically passes 3 images: `guide_sheet_secondary.png`, `out/repaint_primary.png`, `ref/def_ref_2x2.png`, enforcing `IoU >= 0.85`):
```powershell
python -u tools/homm3_retexture_pbr/batch_driver.py paint-api `
  --work-dir $WORK_DIR --manifest $WORK_DIR/renders/batch_<N>_prompts.json --sheet secondary --jobs 4
```
- **Locked Sheet 2 Prompt Template:**
  > Repaint Image 1 (`guide_sheet_secondary.png` — 2x2 orthographic views of `<unit>`: Top-Left = Front 3/4, Top-Right = Rear 3/4, Bottom-Left = Underside/Bottom View, Bottom-Right = Head Closeup) so its colors, markings, eye crispness, fangs/claws, and shading match Image 2 (`repaint_primary.png`) and Image 3 (`def_ref_2x2.png`) seamlessly across angles.
  > HEAD & UNDERSIDE NOTES: `<crisp iris/pupil separation, gumline/fang separation, clean underside/belly/wings matching DEF>`.
  > STRICT LAYOUT LOCK: Preserve the exact pixel silhouette, framing, and solid neutral `#7F7F7F` background in all 4 panels with soft neutral diffuse lighting, zero double-eyes, zero seam smears, and zero text/borders.

*(When using the `$0` Ultra fallback via `image-generator`, save the returned image through `batch_driver.py check-sheet --work-dir $WORK_DIR --unit <unit> --sheet primary|secondary --src <path> --min-iou 0.85` manually and retry once on exit code `2`.)*

### Step 4: CUDA Multi-View Projection & Full-PBR Hex/Lit Bake + QA Board
```powershell
python tools/homm3_retexture_pbr/batch_driver.py project `
  --work-dir $WORK_DIR `
  --units u1:arch1,u2:arch2,u3:arch3,u4:arch4,u5:arch5 `
  --device cuda --parity-unit u1

python tools/homm3_retexture_pbr/batch_driver.py qa-board `
  --work-dir $WORK_DIR `
  --units u1,u2,u3,u4,u5 `
  --shipped-root $SHIPPED_ROOT `
  --out $WORK_DIR/renders/batch_<N>_qa.png
```
Fail-closed invariants inside `project_unit.py` (never relax):
- Multi-view UV projected coverage `>= 75.0%`
- Masked `uv_ao` mean `>= 0.30`
- Giant/seam-sliver UV filter `e_uv > 0.14`
- `--device cuda` parity check vs `--device cpu` (`pos/nrm/tan/dil < 1e-4`, `mask_diff == 0`)

### Step 5: Independent `gemini-4-hydrogen-low` QA + Prune Intermediates
Spawn ONE fresh `gemini-4-hydrogen-low` helper inspecting **ONLY** `$WORK_DIR/renders/batch_<N>_qa.png` via `read_file`, verifying:
1. HoMM3 DEF palette fidelity per unit,
2. Smooth 2K hand-painted PBR brushwork (automatic FAIL if the generator imitated `def_ref_2x2.png` as blocky pixel art, mosaic pixels, sprite dithering, or stair-stepped low-res contours — requires full primary + secondary regeneration),
3. Clean single eye/facial alignment (zero double-eyes, ghosting, or smear streaks),
4. Zero black UV cracks, inside-out dark shells, or seam tears,
5. Crisp Hex/Lit micro-relief & eye/metal sheen without wet-plastic feet.

- On any `FAIL`: fix that unit's failing sheet or archetype, re-run `project` + `qa-board`, re-verify `PASS`.
- Once ALL units in the batch `PASS`, kill the QA helper and immediately free disk space:
```powershell
python tools/homm3_retexture_pbr/batch_driver.py prune-temp --work-dir $WORK_DIR --units u1,u2,u3,u4,u5
```

### Final Slice Assembly & Delivery
Pass `--retexture-dir $WORK_DIR` to `assemble_rebuild_slice.py --smoke-check`, then deploy via `ship_def_retarget_slice.py` (`prepare`, `lab`, `bundles`, `probe`, `deploy`) and run all post-deploy validators. If a `vanilla_style` slice inherits a stale `meshFx` pin and `deploy` fails with `plugin data changed since the runtime record` while `worktree == HEAD == installed`, run `ship_def_retarget_slice.py repin --selection <sel>` then `repin --write` before `deploy`.
