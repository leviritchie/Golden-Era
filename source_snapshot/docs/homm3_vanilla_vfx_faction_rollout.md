# HoMM3 vanilla-style unit effects: per-faction rollout recipe

Status: operational recipe (2026-09-27). The user approved the Conflux set as-is and approved running the remaining
factions in parallel, one agent per faction. The lane contract is `docs/homm3_vanilla_style_effects_rollout.md`, and
the spec schema is the docstring of `tools/homm3_vfx/vanilla_style_fx.py`. This file covers only how a faction agent
works and what it must not collide on.

Proof tier: a faction agent produces **lab-render** evidence only. It does not promote, compile into the catalog,
freeze, deploy or launch the game. The coordinator and fleet own the steps after that, and only the user's in-game
look promotes a unit.

## Per-unit loop

Run every command from the repo root. `<unit>` is the unit-look id, for example `h3_roc`.

1. **Read what the unit ships now.**
   - Read `tools/homm3_unit_look/units/<unit>.json`, which has the defFlipbook, uvAtlas and effectLight layers.
   - Read the unit's row in the inventory section of the rollout doc.
   - Read the unit's candidate rows in `tools/homm3_vfx/vanilla_style/donor_map.json`, if any.
   - Every one of those look layers must be named in the draft's `supersedes.lookLayers`, each with its replacement.
2. **Pick donors** (see the rules below). If a donor prefab is new, add it to the draft first, then probe it:
   `python tools/homm3_vfx/vanilla_style_fx.py sources --extra <resPath> ...`.
   `sources` rebuilds `vanilla_sources.json` from every draft and spec on disk plus `--extra`. The draft must already
   exist, or the next agent's run drops your prefab.
3. **Extract lab recipes** for every source you use: `python tools/homm3_vfx/vanilla_recipes_all.py "<resPath>:<childPath>" ...`.
   - It re-extracts all existing recipes plus yours in one call, under the Unity lock. Never call
     `vanilla_ps_recipe.py` directly: it rewrites `materials.json` and drops everyone else's materials.
   - Use the full childPath when the root's children are inactive, because the walk skips inactive children.
4. **Write the draft** at `tools/homm3_vfx/vanilla_style/drafts/<unit>.json`, schema `homm3_vanilla_style_fx.v1`.
   - Copy the shape of a Conflux draft, for example `h3_ice_elemental.json`.
   - The draft needs exactly one `emissionMap`; black is allowed.
   - Writing the JSON by hand or from a generator in your own scratch is fine. Don't commit the generator.
5. **Write the VANILLA panel refs** at `tools/homm3_vfx/vanilla_style/lab_refs/<unit>.json`.
   - The native body is the donor unit, and `refs` are the donor's own effects on their authored transforms:
     ```json
     {"native": "<donor>", "title": "vanilla <Donor>: what is shown",
      "refs": [{"source": "<resPath>:<childPath>", "transform": "<authored transform name>", "times": null,
                "sourceRootTransform": false, "keep": []}],
      "overlays": [{"source": "<resPath>:<rendererPath>", "materialIndex": 2}]}
     ```
   - `"times": null` means always on; `[0.3, 1.4]` fires at those seconds.
   - Do not add units to `LAB_REFS` in `vanilla_style_lab.py`; a unit in both is refused.
   - A new native body is extracted with
     `python tools/homm3_style_compare/extract_native.py --out artifacts/vanilla_vfx_style/native <faction>/1prefabs/<donor>`.
6. **Validate:**
   - `python tools/homm3_vfx/vanilla_style_fx.py check-drafts`
   - `python tools/homm3_vfx/vanilla_style_fx.py check`
   - `python tools/validate_homm3_vanilla_style_fx_contract.py`
   - All three must pass before a lab run.
7. **Render the lab:** `bash tools/homm3_vfx/vanilla_style_lab_guarded.sh <unit> [<unit> ...] > <your V: scratch>/lab.log 2>&1`.
   - Per unit, the script waits while `HeroesOldenEra` runs, stops below 20 GB free on V:, runs
     `memgate.py --wait 30` and re-checks the game.
   - It then runs `vanilla_style_lab.py --prune-renders`, which takes the Unity lock itself.
   - Output lands in `artifacts/vanilla_vfx_style/lab/<unit>/`: `hero.png`, `idle.png`, `sheet_<clip>.png` and
     `compare.mp4`. Body warp is only visible in the mp4.
8. **Judge and iterate.**
   - Put NEW beside VANILLA. The effect must read at the vanilla unit's scale and density and must not hide the body.
   - Re-render only the units you changed.
9. **Build the comparison sheet:** `python tools/homm3_vfx/vanilla_style_sheet.py --name <faction> <unit> ...`.
   - It writes `artifacts/vanilla_vfx_style/lab/<faction>_comparison.png` and `.json`, and exits 1 when a unit has no
     render.
10. **Commit** your drafts, your `lab_refs/*.json` and the regenerated `vanilla_sources.json`:
    - use `git commit --only -F <msgfile> -- <paths>` (`-F` before `--`: after it, a message file outside the repo is read as a pathspec);
    - check `git diff --cached` first, because the index is shared;
    - the message file is UTF-8 without BOM and ends with the Co-Authored-By line.

    Then report the sheet path to the coordinator.

## Donor-choice rules (learned on Castle and Conflux)

- **Source.**
  - Prefer the donor unit's **own in-unit children**, the effects under `units/<faction>/1prefabs/<unit>` such as idle
    roots, hit/start roots and ability rises, over `magic/prefabs_vfx` target impacts.
  - A target impact put on the caster reads as a detached splash; the monk and pixie v1 both did.
  - For attacks, use the caster-side *start* root, not the target *impact*.
  - `donor_map.json` rows are static candidates. They are not verdicts.
- **Element first, then role.**
  - Idle and always-on effects come from a donor idle child, the attack burst from a hit or start subset, and death
    from a death, rise or smoke subset.
  - Recolour a same-shaped donor rather than pick an off-shape one. A recolour needs a constant start colour on every
    kept node.
  - Materials without `_Color` (every vanilla feather: `magic/test/Disappearance_01` and friends) only take
    `"recolorMode": "multiply"`, which darkens the colour-over-lifetime gradient by `recolor` (each channel at or
    below 1, white start colour). Castle-griffin feathers become the roc's brown this way. Such materials cannot be
    brightened.
- **Subset and scale.**
  - Keep only the `keepNodes` that read.
  - A kept node that has kept descendants needs `zeroChildPositions`.
  - Start at a scale of 0.2-0.5. Impact roots at 0.8 or more engulf the unit; pixie v2 did.
- **Known bad reads.**
  - The `magic_lightning_strike_hex` `Impact` subset renders as blue orbs. For crackle use `qilin_upg`
    `Qilin_upg_idle_Spine` or `mech_guard` `World_watcher_hit_Ring2`.
  - Do not use a Hex/Lit sheet as an overlay; the checker refuses it.
- **Glow is emission, never a light.** A fitted effectLight is superseded by the emissionMap or by a glow particle in
  the kept subset.
- **Clip windows.**
  - Put a DEF shot window on `Unit_ShootFront` and a DEF attack window on `Unit_AttackFront`, just as the DEF has them.
    Since fd25e047ca the owned StockMap plays `Unit_ShootFront` on `15.Skill_1` when the GLB has that clip, and
    `assign_homm3_attack_animation_slots` puts every projectile attack on slot 1 and melee/counter on slot 0. Check
    the delivered `lab_report.json` `stockMap` and the game view: when `15.Skill_1` maps to `Unit_AttackFront`
    (no shot clip), or the view has no projectile attack, the shot window never plays. Record that in `supersedes`
    as "not played". Do not copy it onto `Unit_AttackFront`.
  - Before fd25e047ca, shots played `Unit_AttackFront`. The Conflux ice and frost drafts carried their shot there until
    2026-09-27 and have been moved back. The shipped `h3_storm_elemental` had `shoot_bolt -> none`; it gained its
    `Unit_ShootFront` window on 2026-09-28 (9a4be17219; see the storm note in
    `homm3_vanilla_style_effects_rollout.md`).
  - DEF key k opens at (k + 0.5) / 12 s.
- **Body warp** (`bodyDisplacement`, a FLAG ripple under a baked `COLOR_0.r` mask): draft it wherever the DEF shows the
  body itself flowing (wisps, tails, flames, wing tips) and keep power at or below 0.25.
  - It is **lane-pending**: plan and promotion refuse the unit until the fleet ship step delivers the mask.
  - Leave it out when the unit must be promotable now.
- **Body overlay** (`bodyOverlay`): an effect material appended to the body, such as the Flicker `magic/Fresnel` rim.
  Use it only where the DEF shows the whole body flashing or glowing.

## The tint field (bodyOverlay `colors`)

A bodyOverlay layer can retint its private material copy:

```json
{"id": "psionic_rim", "type": "bodyOverlay",
 "source": {"resPath": "units/undead/1prefabs/flicker_upg", "rendererPath": "Scale_roll/flicker_upg/Flicker_upg",
            "materialIndex": 2},
 "triggers": [{"mode": "always"}],
 "colors": [{"property": "_Color", "rgba": [5.2, 1.0, 3.2, 1.0]},
            {"property": "_EdgeColor", "rgba": [2.8, 0.6, 1.8, 1.0]}]}
```

- **Values.** Colours are absolute HDR values in [0, 16] that replace the native ones. The vanilla green is `_Color`
  (0.13, 3.0, 0.31) and `_EdgeColor` (0, 1.5, 0.72). Match its *luminance* (Rec.709
  weights), not its magnitude: an equal-magnitude magenta rendered at about half the brightness in the lab.
- **Allowed properties.** Each shader has its own list in `OVERLAY_TINT_PROPERTIES` (`vanilla_style_fx.py`). Today
  that is only `magic/Fresnel`: `_Color` and `_EdgeColor`, per its DXBC. Adding a shader is a lane change for the
  coordinator, not a faction edit.
- **Runtime.** The plugin (`Homm3MeshFx.ApplyOverlayTint`) requires each property, writes it, and reads it back before
  it appends the overlay. Any miss disables the row. The contract validator refuses bad tints.
- **Lab.** The lab applies the same tint.
- **Proof.** Psychic is magenta-rose and magic is violet. The tint is compile-checked (live-interop new=0) and lab
  rendered; the in-game look is not proven.

## Shared files: who edits what under parallel runs

| File | Collision | Rule |
|---|---|---|
| `drafts/<unit>.json`, `lab_refs/<unit>.json` | none (one file per unit) | Edit only your own faction's units. |
| `vanilla_style/vanilla_sources.json` | Rewritten whole by every `sources` run | Put the donor into your draft before running `sources`, so later runs keep it. Commit it with your drafts using `--only`; on a conflict, re-run `sources` and commit the result. |
| `artifacts/vanilla_vfx_style/recipes/materials.json` | Rewritten whole by every recipe call | Only through `vanilla_recipes_all.py`, which runs a rebuild-all under the Unity lock. If a lab fails on a truncated `materials.json`, re-run it. |
| `artifacts/vanilla_vfx_style/lab/lab_materials.json`, Unity project `Assets/Homm3VfxLab` | Staged by each lab run | Same content for everyone. Don't hand-edit. |
| Lab shaders and `Homm3VanillaStyleVfxLab.cs`, `vanilla_style_lab.py` (`LAB_REFS`), `vanilla_style_fx.py`, `vanilla_ps_recipe.py`, the contract validator | Shared code | Do not edit. Send the exact change and its evidence to the coordinator. |
| `OfflineUnlockMod/homm3_mesh_fx/catalog.json`, `vanilla_style/units/`, `vanilla_style/compiled/`, `def_flipbook_debt.json` | Promotion, catalog and gate state | Never. Promotion and compile are coordinator/fleet steps. |
| `freeze_slice.py`, `ship_def_retarget_slice.py`, the gates, `homm3_import.json` | Fleet-owned | Never. |
| `donor_map.json`, `docs/homm3_vanilla_style_effects_rollout.md` | Shared records | Report findings to the coordinator, who updates them. |

## Unity lock and machine guards

- **Unity.** It runs only through `tools/homm3_vfx/unitylock.py`, one run at a time on the shared project. The lab
  and `vanilla_recipes_all.py` already take the lock. Check the holder with `python tools/homm3_vfx/unitylock.py status`.
  Parallel agents queue on it, so the lab is the serial step: batch your units into one guarded call.
- **Game process.** Never launch, stop or kill it. The guarded script waits while it runs.
- **Disk and scratch.** Keep scratch on V: (`V:/claude_scratch/<agent>/`), never F: or C:. Stop if V: has under
  20 GB free.
- **Scans.** Never recursively scan `artifacts/` or `V:\homm3_unity_work\Assets`.
- **Cleanup.** `--prune-renders` drops about 1 GB of raw frames per unit. Delete superseded renders of your own units
  only.

## Open factions (2026-09-27)

These are units with defFlipbook layers and no draft yet, from the rollout doc inventory. The inventory lists
defFlipbook units only, so also check each faction's `tools/homm3_unit_look/units/*.json` for uvAtlas- or
effectLight-only units. Castle and Conflux have drafts for every unit.

| Faction | Units |
|---|---|
| stronghold (installed) | `h3_roc`, `h3_thunderbird`, `toa_shahrokh` |
| rampart (installed) | `h3_dendroid_shaman`, `h3_green_dragon`, `h3_gold_dragon`, `h3_diamond_dragon`, `h3_unicorn`, `h3_war_unicorn`, `h3_pristine_unicorn` |
| cove (installed) | `hota_cove_corsair`, `hota_cove_pirate`, `hota_cove_sea_dog`, `hota_cove_nereid`, `hota_cove_nymph`, `hota_cove_oceanid`, `hota_cove_sea_witch`, `hota_cove_sorceress`, `hota_cove_tidecaller` |
| tower (unfrozen) | `h3_mage`, `h3_mage_upg`, `h3_battle_mage`, `h3_genie`, `h3_genie_upg`, `h3_genie_vizier`, `h3_giant`, `h3_giant_upg`, `h3_colossus`, `h3_elemental_gargoyle` |
| inferno (unfrozen) | `h3_efreeti`, `h3_efreet_sultan`, `h3_efreet_sufi`, `h3_hell_hound`, `h3_cerberus`, `h3_fire_hound`, `h3_devil`, `h3_arch_devil`, `h3_arch_demon`, `h3_gog`, `h3_magog`, `h3_amalek` |
| necropolis (unfrozen) | `h3_lich`, `h3_power_lich`, `h3_lich_master`, `h3_vampire`, `h3_vampire_lord`, `h3_vampire_prince`, `h3_wight`, `h3_wraith` |
| dungeon (unfrozen) | `h3_beholder`, `h3_evil_eye`, `h3_fargazer`, `h3_minotaur_taskmaster`, `h3_red_dragon`, `h3_black_dragon`, `h3_shadow_dragon` |
| fortress (unfrozen) | `h3_gorgon`, `h3_mighty_gorgon`, `h3_corrosive_gorgon`, `h3_dragon_fly`, `h3_damsel_fly` |
| factory (unfrozen) | `hota_factory_automaton`, `h3_automaton_upg_alt`, `hota_factory_sentinel_automaton`, `hota_factory_couatl`, `hota_factory_crimson_couatl`, `h3_couatl_upg_alt`, `hota_factory_gunslinger`, `h3_gunslinger_upg_alt`, `hota_factory_bounty_hunter`, `hota_factory_engineer`, `hota_factory_mechanic` (`h3_mechanic_upg_alt` has a shipped spec) |
| bulwark (unfrozen) | `hota_bulwark_shaman`, `hota_bulwark_great_shaman`, `h3_shaman_upg_alt`, `hota_bulwark_jotunn`, `hota_bulwark_jotunn_warlord`, `h3_jotunn_upg_alt` |
