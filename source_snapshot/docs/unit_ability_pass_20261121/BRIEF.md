# Unit ability variety pass: design brief (2026-11-21)

This brief is shared by the faction design agents. Each agent drafts cards only. Nothing gets built until the owner approves the drafts.

## Owner feedback (2026-11-21, verbatim)

> Too many factions have abilities that are shared or effectively shared across many units in their roster, like the 5% per tile damage boost of stronghold and the sweeping strikes of castle. I'm ok with similar such abilities existing across the units for a given faction, but they should not be functionally identical. At minimum they should be quantitatively different, and even better would be if they are qualitatively different (work somewhat differently or have different conditions/limits). Remember how powerful our toolkit is when making this pass, you can and should do some very creative things.
>
> There are some patterns repeated too often across all factions, like too many generic defense buffs, actives that just deal +damage and prevent counters, and long thrust equivalents. I'd like more creativity.

These Castle decisions are fixed. The Castle draft builds around them:

- **Pikeman, Halberdier, Glaivier, Set Pikes:** the counter strikes first only while the stack has not acted yet this round. Waiting and Defending do not count as acting.
- **Halberdier:** Sweeping Halberd is removed. Reaping Arc stays.
- **Glaivier:** Long Thrust is replaced by its former **Guillotine**. That ability (catalog name Execute) deals pure damage equal to 30% of the target creature's max HP, capped by stack size, and is built from `magic_decimate_effect` with `magic_pure`. The owner likes how it works with Castle's Advanced Elite Strategem rank (Compress).

## What counts as a problem

1. **Within a faction**, no two lines may share a functionally identical ability. The Castle and Stronghold examples above show the pattern. Similar abilities are fine if they differ in number. They are better if they differ in kind: a different trigger, condition, limit, target, duration or scaling. An identity keyword shared by both upgrades of one line, such as Ice Immunity on all ram rows, is not a duplicate.
2. **Across the roster**, these patterns are overused. Count them in the current tables (census below) and cut them hard:
   - generic damage-reduction passives (`resist` -x% from melee/ranged/all, 127 rows);
   - actives that are "strike for x% damage, no counterattack" (`melee_strike` with only `mult` and `counter:false`, `castle_strike`, `breath_strike` used the same way);
   - Long Thrust equivalents (`reach_strike`: Long Thrust, Lunge, Lance Reach, Long Reach, Lash, Lash Out, Flame Spit);
   - flat damage-per-hex (`gallop` 0.05, 54 rows);
   - a generic second counterattack (`counters` "Alert", 41 rows);
   - plain whirlwinds (`swirl_strike`, `castle_cleave`).

   Keep HoMM3 identity keywords where HoMM3 had them: Magic Resistance, the immunities, Hatred, Breath, No Retaliation on the creatures that had it, Unlimited Retaliation on the Griffin, Jousting on the Cavalier, Regeneration on the Wight/Troll, Death Stare, and so on. Repeating those is identity, not laziness. A HoMM3 identity can still get a twist if the old one was the generic version.
3. **Replace, don't pile on.** Kit size stays inside the tier range. Bodies may be re-priced: a stronger kit gets a smaller body.

## Design rules (unchanged, see `docs/unit_rebalance_plan_20261120.md` sections 3, 5, 7, 10, 11)

- **Emergent, never wired.** A card reads only battlefield facts any army can produce, never a faction skill or tag. The Glaivier/Compress synergy is emergent: Guillotine scales with target size and does not read Compress.
- **Trade axis.** Each faction's two upgrades split along its trade axis (`tradeAxis` in the table, plan section 5). New cards must sharpen that split.
- **Alternates trade, never ladder.** Same price, at least 3 of 7 stats differ, neither better on every axis, power within 0.10 of each other (unit_power_model).
- **No upgrade stat below its base.**
- **Chance becomes Focus.** No random procs.
- **Native data first.** Plugin rules are invisible to the AI and the damage forecast. Use them where data cannot express the design, and do not shy away from them for signatures.
- Card text uses vanilla wording: Damage, Attack, Defence, Focus, counterattack, round. No "Core", no implementation terms.

## Toolkit (be creative with it)

**Shared keywords** are in `tools/release_port/homm3_unit_design_table.py` (the `kw_*` functions). **Per-faction keywords** are in `tools/release_port/unit_design_keywords/<faction>.py`. **Buff rows** are cloned and edited in the table's `buffs` list (`cloneOf` + `set`), so any buff can carry any stat or data keys.

Native data the Core already ships (a census of the release Core):

- **Triggers:**
  - unit_took_damage, unit_died, start_turn, start_battle, start_round, end_round
  - unit_end_move, unit_skip, unit_wait, continue_after_wait, unit_cast_ability, unit_got_buff
  - buff_timeout, double_turn, cast_magic, cast_magic_start, side_used_energy, crit
- **Condition functions:** allegiance, allegiance_both, ability_and_allegiance, allegiance_receiving_tags, is_active_unit, owner_alive, allegiance_sign.
- **Sequence effects:** counter_before_attack, counter_before_and_after_attack, add_attack_after_counter(_melee/_shoot), disable_counter, skip_turn, return_to_start_after_attack, assist_ability.
- **Mechanics:**
  - Healing and revival: heal, heal_percent, heal_by_hero, heal_from_dispel, revive, vampirism, transfer_hp.
  - Corpses: destroy_corpse_and_heal, destroy_corpse_and_change_mana, destroy_corpse_with_buff.
  - Buff manipulation: dispel, dispel_on_damage, steal_buffs, copy_buff, transfer_buffs, mimic_buffs, add_buff_duration, zero_duration_on_damage, add_duration_on_damage.
  - Movement: teleport, push_unit, push_unit_from_caster, swap_units, random_unit_move.
  - Focus and actions: add_energy, add_action_points, force_unit_cd, force_side_cd.
  - Counterattacks: reduce_counters, add_counters_on_kill.
  - Retaliation damage: revenge_damage, revenge_berserk, take_accumulated_damage.
  - Killing: assasinate, kill_stacks.
  - Summoning: summon_in_pattern, summon_percent, copy_unit, spawn_object (traps).
  - Army-wide: side_buff, global_buff, berserk, substitute_by_hp.
- **Stat keys:** about 70 buff stat keys, among them:
  - taunt radius, untargetable, extra action, damage caps
  - damagePerHex, numCounters, armorPen/attackPen, outDmgModsByTargetTags, inDmgModsByCasterTags
  - overkillProtection, maxOverwatchStrikes, maxInComingNegativeBuffDuration, ignoreShootingBlock
- **Attack patterns:** 45 of them, including swipes, swirls, reach x1/x2, rumbles, lines, cones and jumps.
- **Other shapes:** auras (one per unit), globalPassives (whole side), sideModifiers (hero stats such as mana cost).

To list the exact available keys, read the built Core at `V:/olden_port_work/unit_rebalance/core_overlay_work/Core.zip`. It holds DB/units, DB/buffs, attack patterns and hero sub-skills; read it with Python zipfile and do not extract it.

**Plugin lanes**, all in `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/`:

- `Homm3UnitKitRuntime.cs` applies damage-step rules per unit. The rule table is generated by `tools/release_port/build_unit_kit_runtime_table.py`.
  - Existing rules: damage_vs_buff, grudge, adjacent_ally_ward, hit_cap, loss_fury, death_toll.
  - New rule kinds are cheap: one enum value plus a few lines.
- The buff-add hook rewrites buffs: `rotate` and `escalate`.
- Round, action, skip and wait dispatchers, and ability commit, can be hooked; the Stronghold Warcry runtime already uses them. This allows rules such as "has not acted this round", "moved this turn", "first attack this round" and "acted before the target".
- Queued free attacks use the same attack queue as Avenger. Covering Fire, a reaction shot, is built on it.

Power: `tools/release_port/unit_power_model.py`. Kit entries can carry `offMult`/`toughMult` for what the model cannot see. Quick check: `python tools/release_port/unit_design_lab.py check --faction <faction>`, which takes seconds. Do NOT run `tune --write`.

Also read the three `docs/vanilla_faction_*_design_philosophy.md` files for how vanilla Olden Era makes units feel distinct.

## Census of the current tables (keyword: rows)

| Keyword | Rows |
|---|---|
| resist | 127 |
| keep_ability | 67 |
| gallop | 54 |
| card | 52 |
| counters | 41 |
| melee_strike | 40 |
| on_hit_buff | 32 |
| no_retaliation | 27 |
| shot | 23 |
| hatred | 16 |
| effect_immunity | 15 |
| stat_aura | 13 |
| sharpshooter | 13 |
| skirmisher | 12 |
| runtime | 11 |
| self_buff | 10 |
| aura | 9 |
| swirl_strike | 9 |
| reach_strike | 9 |
| double_strike | 9 |
| stronghold_armor_rend | 8 |
| rally | 7 |
| dive | 6 |
| castle_cleave | 6 |

`keep_ability` keeps an old active from before the rebalance. Look at what it actually keeps (the unit's view/logic rows in the built Core) and judge it the same way.

## Deliverable

Write one file per faction at `docs/unit_ability_pass_20261121/<faction>.md`, for example `castle.md`. Do not edit the design tables, keyword modules or plugin code.

Each faction file contains:

1. **Duplicates found:** a short table, ability → units → why it is a duplicate or generic.
2. **Proposed kits:** one row per unit (all 21, or as many as the faction has), with columns:
   - unit
   - card name
   - P/active with Focus and cooldown
   - the exact card text as the player will read it
   - how it is built: existing keyword with parameters, or a new keyword/plugin rule named and specified in one line
   - what it replaces
   
   Mark cards that stay unchanged as "kept".
3. **New mechanics needed:** a deduplicated list of new keywords, buffs and plugin rule kinds with a one-paragraph spec each, including the native donor rows you would clone, verified by reading the Core.
4. **Power notes:** which bodies should shrink or grow and roughly by how much. Use `unit_design_lab.py check` only on a scratch copy of the table (`--design <path>`); scratch files go under `V:/olden_port_work/unit_rebalance/ability_pass/`.
5. **Risks:** anything unproven in game.

Aim for distinct, memorable abilities. Each one should change how the player positions or sequences that stack. Keep the HoMM3 flavour of the creature.

Compare across the factions assigned to you as well, so you do not hand two factions the same new trick.
