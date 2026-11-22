# Unit ability pass: plugin runtime contract (2026-11-21)

This file is for the faction lanes. It lists every plugin rule kind still live after `REVIEW.md` section 7 and `HIDDEN_CAP.md`, and the exact kit-entry shape the generator (`tools/release_port/build_unit_kit_runtime_table.py`) accepts. The plugin side is `Homm3UnitKitRuntime.cs` (damage step, buff-add rewrites) and `Homm3UnitKitBattleHooks.cs` (dispatchers, attack queue, commit hook, H hooks).

## Shape

Every rule is one kit entry on the unit row:

```json
{"k": "runtime", "rule": "<kind>", "percent": 25, "name": "Card Name", "text": "...", "icon": "...", ...params}
```

- `percent` is required: a positive integer. Use 1 for rules with no number (the doc says which).
- `name` is required (it is the log label and the card name).
- Unknown parameters are rejected, so a typo fails the generator instead of silently doing nothing.
- Fusions (owner decision 1, option A) do not inherit any runtime rule. Nothing to write for them.

### Shared optional parameters (damage-step rules marked "filters: yes")

| Param | Values | Meaning |
|---|---|---|
| `attack` | `"any"` (default), `"melee"`, `"ranged"` | Which of the holder's hits count. Ranged = the committed attack is a shot (attack type shoot/range); melee = everything else that is an attack. Counterattacks count unless `abilityOnly`. |
| `abilityOnly` | `true` / `false` (default) | Only hits of the holder's own active ability (an `Ability` commit, not a basic attack, alternative attack or counterattack) count. |

## Rule kinds

### Damage step, holder deals damage (contributes a percent to the committed hit)

| Rule | Params | Meaning | Cards |
|---|---|---|---|
| `turn_state` | `fact`: `"stood_ground"`, `"unacted_target"`, `"moved_target"`, `"waited_target"`; filters: yes | `stood_ground`: the holder did not move during its previous action (true before its first action). `unacted_target`: the target has not yet taken an action this round (Wait does not count as acting; Defend does). `moved_target`: the target moved this round (its own move, including the move into a melee attack it is making right now). `waited_target`: the target Waited this round. | Stand Ground (`stood_ground`, `attack: "ranged"`), Ambush (`unacted_target`), Run Down x3 (`moved_target`) |
| `counter_state` | `state`: `"left0"` or `"used"`; filters: yes | `left0`: the target has no counterattack left this round (its counterattacks this round, as seen by the plugin, reached its per-round count, or it has a counter-disabling effect the plugin can read). `used`: the target has counterattacked at least once this round. | Pulverize (`left0`, `abilityOnly: true`) |
| `adjacency` | `mode`: `"flank"` or `"isolated"`; filters: yes | `flank`: the target stands next to at least one friendly stack of the holder other than the holder. `isolated`: no stack of the target's own side stands next to the target. | Pack Hunt x3 (`flank`) |
| `crowd` | `cap` (required, >= percent); filters: yes | +percent for each enemy stack adjacent to the holder beyond the first, at most +cap. Hellfire Burst: `inferno_nova` mult 0.4 + `crowd` percent 100 cap 300 gives 40% x adjacent enemies, up to 160%. | Hellfire Burst (`abilityOnly: true`) |
| `hit_this_round` | `cap` (required, >= percent); filters: yes | +percent for each other friendly stack (holder's side, not the holder) that has damaged the target this round, at most +cap. | Swarm Fire |
| `first_hit` | `side`: `"attacker"` or `"defender"` | `attacker`: the holder's first attack or counterattack each round deals +percent (every hit of that one attack). `defender`: the first attack against the holder each round deals -percent to it (any unit attack; spells and damage over time with no unit attack are not "attacks"). | Opening Gust (`attacker`), Stubborn Fleece (`defender`) |
| `damage_vs_buff` | `buffs` (required list of buff SIDs); filters: yes | +percent when the target has one of the buffs. | Death Blow (`abilityOnly`), Gorgon alt Gore (`abilityOnly`), Run Aground |
| `damage_vs_hp` | `below` (required int 1..99); filters: yes | +percent when the target's current stack Health is below `below`% of its full Health (the largest total the plugin has seen for it this battle). | Exsanguinate (`below: 50`, `abilityOnly: true`) |
| `bounty` | filters: yes | +percent when the target has the most current total Health of all living enemy stacks (ties count). | Bounty |
| `retribution` | filters: yes | +percent when the target damaged any stack of the holder's side (the holder included) earlier this round. | Retribution (Monk, Zealot) |
| `same_target_streak` | `cap` (required, >= percent); filters: yes | Each attack on the same stack as the holder's previous attack adds +percent, at most +cap; an attack on another stack resets to 0. The first attack on a stack gets nothing. | Relentless Blades (percent 15, cap 45) |
| `stored_fury` | `cap` (required, >= percent) | Each attack the holder takes adds +percent to its next attack or counterattack, at most +cap. That attack uses it all up. | Pent-up Fury (percent 10, cap 50) |
| `quarry` | `buff` (required SID of the visible mark buff); filters: yes | +percent against the stack the holder most recently put `buff` on, while that stack lives. Marking another stack moves the quarry. The plugin keeps the pair (from the buff-add hook); the buff is only the visible marker. | Quarry (percent 35, buff `h3_kit_fortress_quarry_effect`) |
| `wall_slam` | filters: yes | +percent when the hex directly behind the target (away from the holder) is blocked: an obstacle, any stack, or the battlefield edge. Read before the push lands. | Wall Slam (percent 50, `abilityOnly: true`) |
| `grudge` | none | (existing) +percent vs a stack that damaged the holder earlier in the battle. | none live after HIDDEN_CAP (Grudge is native now) |
| `loss_fury` | `cap` (required, 1..percent) | (existing) +percent per 100% of the own stack lost this battle, at most +cap. | Revenge (Haspid) |
| `death_toll` | `cap` (required, >= percent) | (existing) +percent per stack fallen this battle, at most +cap. | none live after HIDDEN_CAP (Grave Tide is native now) |

### Damage step, holder takes damage

| Rule | Params | Meaning | Cards |
|---|---|---|---|
| `adjacent_ally_ward` | `cap` (required, >= percent) | (existing) -percent per adjacent friendly stack, at most -cap. | Shield Wall |
| `hit_cap` | percent < 100 | (existing) one hit deals at most percent% of the stack's full Health. | Diamond Scales |
| `bodyguard` | none (percent = share) | **H.** When an adjacent friendly stack takes Damage from a unit attack, percent% of that hit is taken off it and dealt to the holder instead. | Guardian Protocol (percent 30) |

### Attack queue (free attacks the plugin queues)

| Rule | Params | Meaning | Cards |
|---|---|---|---|
| `guard_strike` | `perRound` (int >= 1, default 1) | When an enemy attacks a friendly stack adjacent to the holder in Melee (not the holder, not a counterattack), and the holder also stands next to that enemy, the holder strikes it with a free melee attack dealing percent% Damage after the attack. At most `perRound` per round. | Shield Brother (percent 50, `perRound` 1; alt `perRound` 2) |
| `zone_shot` | `radius` (int >= 1), `perRound` (int >= 1, default 1) | When an enemy stack's move ends within `radius` hexes of the holder, the holder shoots it for percent% Damage before that enemy attacks. The holder must be able to shoot (a ranged attack, no enemy adjacent). At most `perRound` per round. | Vigilant Eye (percent 60, radius 3) |
| `spell_echo` | `perRound` (default 1) | **H.** When the holder's hero casts a spell or hero ability whose target hexes hold an enemy creature, the holder shoots that creature for percent% Damage. | Arcane Volley (percent 50) |

### Hooks on movement, commits and kills

| Rule | Params | Meaning | Cards |
|---|---|---|---|
| `arrival_buff` | `buff` (required SID), `radius` (int >= 1, default 1) | percent 1. An enemy stack whose move ends within `radius` hexes of the holder gets `buff` (cast by the holder) when its action ends. | Scorched Earth (buff `h3_kit_inferno_scorched_effect`) |
| `kill_extra_action` | `buff` (required SID of a buff carrying `add_action_points ["1"]` and room in `maxAddedApPerRound`), `abilityIndex` (optional int: only that ability slot) | percent 1. When the holder's active ability destroys the stack it hit, the holder gets `buff` at once (one more action this round). Once per round. | Deathly Plunge |
| `ability_feedback` | `radius` (int >= 1) | When an enemy stack within `radius` hexes of the holder hits with its active ability, it takes Damage equal to percent% of the holder's basic attack Damage (stack count x average damage), dealt straight to it after that hit (no Defence). Abilities that deal no damage do not trigger it (limit of the hook). | Psychic Feedback (percent 30, radius 3) |
| `brand_splash` | `buff` (required SID of the brand buff) | Whenever a stack carrying `buff` takes Damage from a unit attack, every stack of its own side adjacent to it takes percent% of that hit afterwards. Splash damage never splashes again. | Brand of Faith (percent 25, buff `h3_kit_castle_brand_effect`) |
| `charge_no_counter` | `hexes` (int >= 1) | **H.** percent 1. When the holder's melee attack follows a move of at least `hexes` hexes (path length) in the same action, the target does not counterattack. | Unhorse (hexes 4) |
| `scatter` | `hexes` (int 1..3) | **H.** percent 1. After the holder survives a Melee hit from an enemy stack, it moves up to `hexes` hexes directly away from that attacker, as far as the hexes are free. | Flutter Away (hexes 1; alt 2) |
| `raise_by_hp` | `buff` or none | **H.** Not implemented: use the draft fallback (see the plugin handback). | Raise Demons |

### Buff-add rewrites (any kit entry that has a `"buff"`)

| Key | Shape | Meaning |
|---|---|---|
| `rotate` | `[sid, ...]` | (existing) each use of the buff becomes the next listed buff. |
| `escalate` | `{"to": sid, "unless": sid?}` | (existing) a repeat on a target that still has the buff becomes `to`. |
| `escalate` | `{"chain": [sid2, sid3, ...]}` | New: stacking by distinct SIDs. Applying the buff to a target that already has it adds the first chain buff it lacks; once it has all, the last one refreshes. Use for "+5% per stack, up to N": the buff plus N-1 copies, each with the same stat. Bloodied Fury: 1 + 7; Grave Tide: 1 + 5. |
| `scale_by_caster` | `{"percent": 40, "tiers": [[damage, sid], ...]}` | New: the plugin computes percent% of the caster's basic attack Damage (stack count x average of damageMin/damageMax) and adds the tier buff with the largest `damage` not above it (the lowest tier when none is). Tiers are ascending; each tier buff deals that fixed `damage` per tick. Ignite: buff `h3_kit_conflux_ignite_effect` with tiers. |

A buff may carry only one of `rotate`, `escalate` or `scale_by_caster`.

## Withdrawn kinds (the generator rejects them)

`overkill_carry` (owner decision 4), `vs_buff_tag` / `vs_debuffed` / `vs_buffed` (Cripple and Siege Breaker are native), `unhurt` (Deadly Sting is native), `outnumbered` (Smite is native), `duel_mark` (Challenge is native), `kill_refund` (owner decision 4 restored `kill_extra_action`). Old draft names map to the merged kinds: `stood_ground`, `unacted_target`, `target_not_acted`, `moved_target`, `waited_target`, `allies_acted` -> `turn_state`; `no_counter_left`, `spent_counter` -> `counter_state`; `flank`, `isolated` -> `adjacency`; `crowd_nova` -> `crowd`; `focus_fire` -> `hit_this_round`; `first_hit_ward` -> `first_hit`; `overwatch` -> `zone_shot`.

## Proof tier

Build only. Every hook fails closed: a read failure gives no bonus, and a hook that throws disables its rule for the rest of the session and logs once. The AI and the damage forecast do not see any of these rules.
