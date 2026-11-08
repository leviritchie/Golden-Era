# Parallel faction rollout: worker brief

Status: operational brief for the parallel DEF-retarget faction rollout (from 2026-09-27). Proof tier of everything a
worker produces: generated artifact. Installs are done by the coordinator only.

## Ownership

| owner | factions |
|---|---|
| fleet agent (tool owner) | stronghold, rampart, castle leftovers, conflux, and the shared tools |
| worker A | tower, necropolis, inferno, dungeon |
| worker B | fortress, bulwark, factory, cove |

- Only the fleet agent edits shared code and data, including `tools/homm3_def_retarget/*.py`, the shared exts,
  `stride_match_glb.py`, `ship_def_retarget_slice.py`, the gates and validators, and
  `custom_factions/.../homm3_import.json`.
  - A worker that needs a shared change sends the coordinator the exact change and the evidence. The coordinator
    routes it.
  - A new ext is a *new file*. A per-unit knob (for example `strideMatch.maxDrop` or `highHarmonicKeep`) goes in
    the unit's own config, fails closed and carries a reason.
- A worker touches only its own factions' unit configs and artifacts.

## Quality pass (a unit is done when every item holds)

- **Mesh identity** matches the DEF: the right creature, no swapped basename. Check it before spending builds.
- **Articulation gate** passes, including jitter p90 ≤ 0.35 and the wing range for fliers.
  - Wing range is judged by the rule `flyer_articulation.wing_rule()` names, and the census and freeze facts stamp
    it. With no DEF row (`flatFloor`), the wing range and the swing from frame 0 must both reach 60°. With a
    DEF-measured row in `reference/def_wing_range.json` (`defRow`), the range must reach 0.8 × the DEF's range in
    place of the 60° floor. The user approved this on 2026-09-27: "I approve the 80% wing beat concept". Where
    0.8 × the row falls under 60° (a low-flap DEF), the upper end of the row's bracket is used
    (`defRowUpperBound`). No row means no relaxation. Rows come only from the validated calibration tool.
  - Teleporters (`moveRule` = `teleportMove`) skip only the Move swing floors, and only when both hold: the flier
    table lists `movementTeleporting` and the DEF Move is exactly 1 frame (h3_devil, h3_arch_devil, h3_arch_demon:
    MoveStart vanish, Move 1 frame, MoveEnd appear). Jitter and the freeze gate on MoveStart/MoveEnd still apply.
    This is a DEF-relative exemption like `strideExempt`, not a relaxation for any unit that walks in its DEF.
  - **Facing** is measured by one rule per rig class, stamped as `facingRule`: `lateralPair` (arm, upleg or
    shoulder pair), `wingPair` (`Wing*L_00`/`Wing*R_00`), or `headAxis` (the Head bone's +Y, horizontal share at
    least 0.5). An unmeasurable rig fails.
- **Stride gate** passes on walkers: slip ≤ 0.686, ratio ≤ 1.4, cadence ≤ 1.6. Legless and floating units need
  an explicit exemption with a reason.
- **Facing**: the delivered GLB idle0 faces +Z.
- **Look stamp** is current on the canonical GLB. Effects are vanilla style, never DEF-ripped flipbooks.
- **No refine jitter.** Any Hips translation above 4 Hz on Death or Hitted is reported.
- **Never loosen a gate to pass.** A unit that can't pass is reported with its numbers.
- **Judge the render sheet, not only the numbers.** Freeze-then-pop, floating bodies and detached props are fails.

## Run discipline

- Before every Blender or Unity launch, use a guarded runner:
  - wait (launch nothing) while `HeroesOldenEra.exe` is running;
  - stop if V: has under 20 GB free;
  - run `python tools/homm3_def_retarget/memgate.py --wait 30`;
  - re-check the game just before launch.
  - The chain must actually stop on a failed check. Model: `F:/claude_scratch/aeba/guarded.sh`.
- Build one unit at a time per worker. Memgate arbitrates between the workers.
- New scratch, probes and side builds go on V: (`artifacts/claude_takeover_20260927/<worker>/`). Never C:. The user's 2026-09-27 instruction supersedes the former F: placement because that drive is too slow for routine work. Existing F: artifacts remain evidence; do not move or delete them indiscriminately.
- Never launch, stop or kill the game.
- Launch Unity only via `tools/homm3_vfx/unitylock.py`.

## Cleanup (required, not optional)

- When a unit passes, remove its own superseded outputs. Keep only what its canonical chain and the census point
  at. Use the existing prune paths first (for example `look.py --prune-superseded`), and delete side builds and
  probes on F: once a decision is recorded.
- Never delete another worker's or faction's files, anything a `*_slice_v1.json` selection or runtime record
  points at, or anything under a `_superseded_do_not_use` folder.
- Report GB freed per faction in the pass table.

## Hand-back per faction

- A pass table with one row per unit: identity, articulation (jitter, wing range), stride (slip, ratio, cadence),
  facing, look, knobs used with reasons, thin margins, and GB freed.
- The freeze command line, which the coordinator runs. Workers never run `freeze_slice.py` or `deploy`.

## Commits

- Use a scoped `git commit --only -F <msgfile> -- <paths>`. The message file is UTF-8 without BOM.
  Attribute the actual contributors; the previous Claude footer is not an instruction to attribute a new agent's work to Claude.
- Check `git diff --cached` first. The index is shared. Never `git add -A`, push or amend.
