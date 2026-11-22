# Unit ability variety pass: build brief (2026-11-21)

The owner approved the pass and asked for everything to be built and installed. This brief is for the build lanes. One lead session merges the lanes, builds, installs and commits.

## What to build

The approved design is these documents, applied in this order (later ones win):

1. The faction draft `docs/unit_ability_pass_20261121/<faction>.md`.
2. `REVIEW.md`, sections 1 to 4. Overrides are marked **(R)**. This includes the within-faction removals and the renames.
3. `REVIEW.md` section 7 (owner decisions): kill → act again, the resist-replacement table, the Stronghold and Castle conversions, and the fusion rule.
4. `HIDDEN_CAP.md`: conversions of hidden damage conditionals.

`BRIEF.md` still holds the rules: emergent not wired, trade axis, alternates trade and never ladder, no upgrade stat below its base, no random procs, and vanilla card wording.

## Lane rules (several lanes run at the same time)

- **Files you may edit:**
  - `custom_factions/unit_designs/homm3_<faction>.json` for your factions only.
  - `tools/release_port/unit_design_keywords/<faction>.py` for your factions only. Dungeon's module is `h3dungeon.py`.
  - `custom_factions/unit_designs/card_icons/card_icons_<faction>.json`, a staging fragment you create. Same shape as `card_icons.json`: `{"cards": {"<section>/<name sid>": {"icon": "<sprite>", "why": "..."}}}`.
- **Files you must not edit:** `homm3_unit_design_table.py`, other factions' files, `card_icons.json`, the artificing policy and catalog, plugin C# files and `build_unit_kit_runtime_table.py`.
  - A keyword that several factions need goes in your own faction module. Copy the helper if necessary.
  - The lead merges icons and artificing.
- **Never commit, never install, never launch or kill the game.**
- **Scratch:** use `V:/olden_port_work/unit_rebalance/ability_pass/<faction>/`. Never scan V:, F: or iCloud recursively.
- **Plugin rules:** write them as `{"k": "runtime", "rule": "<kind>", ...}` kit entries.
  - Use the rule kind names and parameters from `REVIEW.md` §4.1, e.g. `"rule": "turn_state", "fact": "moved_target", "percent": 20`.
  - Every runtime entry needs a positive integer `percent`. Use 1 for non-damage rules, and add an explicit `"scope"` or other parameter where the rule needs one.
  - The plugin lane implements the kinds. The generator (`build_unit_kit_runtime_table.py`) will reject unknown kinds until that lane lands. Ignore that failure; the overlay build does not run the generator.
  - Plugin-only cards (H hooks: charge_no_counter, scatter, bodyguard, spell_echo, raise_by_hp) are built the same way. In your handback, give each one's native fallback from its draft.
- **Buffs:** add new buffs as `cloneOf` + `set` rows in the faction's `buffs` list. Check that donors exist by reading `V:/olden_port_work/unit_rebalance/core_overlay_work/Core.zip` with Python zipfile. Do not extract it.
- **Class tags:** the builder now adds unit tags `h3_kit_undead`, `h3_kit_demon`, `h3_kit_shooter` and `h3_kit_flyer` (`apply_design_tags`). Use them for tag-keyed damage mods (`outDmgModsByTargetTags` / `inDmgModsByCasterTags`). Per-card tags such as `h3_kit_challenger` go on the unit row via your keyword.
- **Card icons:** every new or renamed card needs a sprite.
  - Use an existing vanilla sprite from `custom_factions/unit_designs/card_icons/card_icon_pools.json`.
  - Passives take a glyph from the `glyph` pool; actives and alternative attacks take a painted icon from the `painted` pool. Pick by meaning (no bow on a melee card).
  - Write the entry in your fragment. Delete fragment entries for cards you removed only if they are in your fragment; the lead prunes `card_icons.json`.
- **Power:** after each faction run `python tools/release_port/unit_design_lab.py check --faction <faction>` until it reports 0 errors.
  - Re-price bodies from the draft power notes and the review's +5-8% bumps on "drop" rows.
  - Alternates must stay within 0.10 power of each other.
  - Never run `tune --write`.
- **Build test:** once all your factions pass the lab, run the overlay dry-run into your own work dir. Allow about 10 minutes.

  ```
  python tools/release_port/apply_release_core_overlay.py --dry-run --game-target steam_26615913 --work-dir V:/olden_port_work/unit_rebalance/ability_pass/<lane>/core_overlay_work
  ```

  Another lane's half-finished table can break the build. If the error names another faction, wait a few minutes and retry. If it names yours, fix it. The build must pass for your factions.
- **Unknowns.** Wave 0 in REVIEW §6 lists the native combinations nobody has proven in game. Build them as designed; in-game checks happen after install. Where a draft names a fallback, record it in your handback.

## Handback (short)

- Per faction: cards added, removed and renamed (counts), plus body changes.
- Every runtime entry you wrote: unit, rule, params.
- H-hook cards with their fallbacks.
- Unknowns you could not verify.
- The lab result and the build result.
