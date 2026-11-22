# Dungeon (homm3_dungeon): ability variety draft

Draft only (2026-11-21). Nothing here is built. Trade axis is unchanged: **Reckless** (striker: hardest hitters, thin bodies, self-inflicted exposure) versus **Sustained** (ward: drain, regeneration, no-counterattack strikes, control).

**Faction verb: timing.** Dungeon cards read *when* in the round something happens: a target that has not acted yet (Ambush), a target that already spent its counterattack (Carrion Wings), an enemy stepping into a watched zone (Vigilant Eye), a counterattack that slows the next turn (Stiffening Glare). The faction also controls *where* units stand: Bull Rush and Wall Slam push targets, and Cave-In drops rubble. Push and terrain belong only to Dungeon among my three factions. Inferno got swap, and Necropolis got root.

## 1. Duplicates found

| Ability | Units | Why it is a duplicate or generic |
|---|---|---|
| `gallop` (Pounce, Gore) | minotaur_upg, manticore line (all three) | The same damage-per-hex on two lines. |
| `counters` "Alert" | minotaur, minotaur_upg, minotaur_upg_alt | A whole line with the generic second counterattack. |
| Generic `resist` (Elusive, Thick Hide, Chitin, Black Scales) | harpy_upg, minotaur_upg_alt, manticore_upg, red_dragon_upg | Flat reduction on four lines. Black Scales also stacked on top of the Black Dragon's spell immunity. |
| `regeneration` | minotaur_upg_alt | Regeneration is the Necropolis Wight identity (one of my factions) and the Troll's. |
| Strike +x% actives (Withering Ray, Rending Maws, Savage, Shadow Rage, Lunge as reach) | beholder_upg, manticore_upg_alt, red_dragon_upg_alt, medusa_upg_alt | Plain "hit harder" or reach buttons. |
| Blood Frenzy / Savage / Shadow Rage | troglodyte_upg, manticore_upg_alt, red_dragon_upg_alt | Three different names for "more Damage when something bled". |
| Swoop, Shadow Flame, Ancient Vigor | red_dragon line | Piled-on cards past the tier's kit size. |
| Distant Watcher, First Glance | beholder_upg_alt, medusa_upg | Static distance/first-hit damage modifiers that do not change positioning. |
| Tunnel Breaker, Tunnel Feast | troglodyte line | Generic damage modifiers with no HoMM3 hook. |

## 2. Proposed kits

| Unit | Card | P / active | Card text | How it is built | Replaces |
|---|---|---|---|---|---|
| h3_troglodyte | (all cards) | | kept | kept | kept |
| h3_troglodyte_upg (Infernal) | Sightless | P | kept | kept | kept |
| h3_troglodyte_upg | Ambush | P | Deals +30% Damage to stacks that have not acted yet this round. Takes +15% Damage from basic attacks. | new kw `h3dungeon_ambush`: new runtime rule `unacted_target` {percent 30} plus the existing `h3dungeon_reckless` taken half (melee/ranged basic taken 0.15) | Blood Frenzy, Tunnel Breaker |
| h3_troglodyte_upg_alt | Sightless, Burrow, Transport | | kept | kept | kept |
| h3_troglodyte_upg_alt | Cave-In | 2 Focus, CD 3 | Collapses the ceiling on an empty hex within 4 hexes, leaving rubble that blocks movement for 2 rounds. | new kw `h3dungeon_cave_in`: hex-target cast using `summon_in_pattern` obstacle `cave_in_obstacle` (verified donor: `battle_primal_magics[7]`) | Tunnel Feast |
| h3_harpy | (all cards) | | kept | kept | kept |
| h3_harpy_upg (Harpy Hag) | No Retaliation, Hit and Run | P | kept | kept | kept |
| h3_harpy_upg | Carrion Wings | P | Deals +30% Damage to stacks that have already counterattacked this round. | new runtime rule `spent_counter` {percent 30}: reads the target's counters used this round | Elusive |
| h3_harpy_upg_alt | Double Strike, Reckless Dive | | kept | kept | kept |
| h3_beholder | (all cards) | | kept | kept | kept |
| h3_beholder_upg (Evil Eye) | Many Eyes, Unblinking | P | kept | kept | kept |
| h3_beholder_upg | Ray Barrage | 2 Focus, CD 2 | Fires rays at up to 3 different enemy stacks, each taking 50% Ranged Damage. They do not counterattack. | new kw `h3dungeon_ray_barrage`: `shot`-type ability with `multicast` numTargets 3 (verified donor: `bonus_magic_pure_bolt`), mult 0.5, damage type physical ranged | Withering Ray |
| h3_beholder_upg_alt | Many Eyes, Sharpshooter | P | kept | kept | kept |
| h3_beholder_upg_alt | Vigilant Eye | P | Once per round, shoots the first enemy that ends its move within 3 hexes for 60% Damage. | new runtime rule `overwatch` {radius 3, mult 0.6, perRound 1}: the enemy end-of-move dispatcher pushes a shot onto the Avenger/Covering Fire attack queue | Distant Watcher |
| h3_medusa | (all cards) | | kept | kept | kept |
| h3_medusa_upg (Medusa Queen) | Coils, Sharpshooter, Stone Gaze | | kept | kept | kept |
| h3_medusa_upg | Stiffening Glare | P | Counterattacks give the attacker -2 Speed and -2 Initiative until the end of the next round. | `on_hit_buff` with a new `buckets ["counter"]` parameter (counterattacks only), buff `h3_kit_h3dungeon_stiffened_effect` (cloneOf `hydra_debuff`, speed -2, initiative -2, maxDuration 2) | First Glance |
| h3_medusa_upg_alt | Serpent's Wrath, Petrifying Strike, Slither Away | | kept | kept | kept (Lunge removed) |
| h3_minotaur | Bravery | P | kept | kept | kept |
| h3_minotaur | Bull Rush | 2 Focus, CD 2 | Performs a Melee attack and pushes the target 1 hex directly away. | new kw `h3dungeon_bull_rush`: clone of `minos_l` ability 0 (verified: melee strike with `push_unit_from_caster ["false"]`, triggerCounter false, energy 2, cd 2) | Alert |
| h3_minotaur_upg (Minotaur King) | Bravery | P | kept | kept | kept |
| h3_minotaur_upg | Wall Slam | 2 Focus, CD 2 | Performs a Melee attack and pushes the target 1 hex away. If the hex behind the target is blocked by an obstacle, a stack or the battlefield edge, the attack deals +50% Damage. | `h3dungeon_bull_rush` + new runtime rule `wall_slam` {percent 50, abilityOnly}: checks the push destination before the push resolves | Alert, Gore |
| h3_minotaur_upg | Headlong | P | Melee attacks deal +15% Damage. Takes +15% Damage from basic attacks. | existing `h3dungeon_reckless` {out 0.15 melee, taken 0.15} | gallop |
| h3_minotaur_upg_alt | Bravery, Earthshatter | | kept | kept | kept |
| h3_minotaur_upg_alt | Immovable | P | Cannot be pushed, pulled, swapped or rooted. | existing `effect_immunity` movementNegative (plus the push mechanic exclusion, see section 3) | Alert, Thick Hide, Regeneration |
| h3_manticore | Venom | P | kept | kept | kept (Pounce removed) |
| h3_manticore_upg (Scorpicore) | Venom, Blood Feast, Paralyzing Sting | | kept | kept | kept (Pounce, Chitin removed) |
| h3_manticore_upg_alt | Venom, Triple Maw | | kept | kept | kept |
| h3_manticore_upg_alt | Venom Burst | 2 Focus, CD 2 | Performs a Melee attack. Afterwards every Damage-over-time effect on the target deals its Damage immediately. | `melee_strike` mult 1.0 + targetMechanics `activate_all_buff_actions ["overTime_effect"]` (verified native on `mummy_l` and `lich_upg_l`. The h3 Venom buff already carries the `activate_all_buff_actions_damage` tag.) | Savage, Pounce, Rending Maws |
| h3_red_dragon | (all cards) | | kept | kept | kept |
| h3_red_dragon_upg (Black Dragon) | Dragonbreath, Spell Immunity (5), Hatred of Titans, Dragonflight | | kept | kept | kept (Black Scales, Ancient Vigor removed) |
| h3_red_dragon_upg_alt | Dragonbreath, Spell Immunity (4), Hatred of Titans, Withering Bite | | kept | kept | kept (Shadow Rage, Swoop, Shadow Flame removed) |

## 3. New mechanics needed

- **Runtime rule `unacted_target`** {percent}: +percent when the target has not taken an action yet this round. This uses the action dispatcher stamp that Stronghold Warcry and the Castle Set Pikes rule already read. Waiting counts as acting, which is the opposite of the Castle Set Pikes rule; it fits Dungeon's "strike first" timing.
- **Kw `h3dungeon_ambush`**. Wraps `unacted_target` + the `h3dungeon_reckless` taken penalty in one card.
- **Kw `h3dungeon_cave_in`**. A hex-target cast with `summon_in_pattern` obstacle `cave_in_obstacle` (verified in `battle_primal_magics[7]`). Lifetime 2 rounds.
- **Runtime rule `spent_counter`** {percent}: +percent when the target's counterattacks used this round ≥ 1 (or its counters remaining is 0).
- **Kw `h3dungeon_ray_barrage`**. A ranged ability using the `multicast` block from `bonus_magic_pure_bolt` (verified `numTargets 3`) on a physical shot, mult 0.5, no counterattack.
- **Runtime rule `overwatch`** {radius, mult, perRound}. Trigger: an enemy stack ends a move within radius. Effect: queue one 60% shot from this unit on the Covering Fire attack queue. The queue already exists (Rampart Grand Elf); only the trigger is new. Native `maxOverwatchStrikes` (`qilin_upg_alt`) and the Formation overwatch buff were checked and are melee-zone only, so they cannot express a ranged trigger.
- **`on_hit_buff` `buckets` parameter**. Restricts the on-hit buff to counterattacks only. This is a data change in the keyword: the action condition becomes the counter attack type.
- **Kw `h3dungeon_bull_rush`**. Clone of `minos_l` ability 0 (verified: vanilla Dungeon minotaur push, `push_unit_from_caster ["false"]`).
- **Runtime rule `wall_slam`** {percent, abilityOnly}: on this unit's ability, +percent if the hex the push would move the target into is an obstacle, an occupied hex or off the field.
- Reused: `h3dungeon_reckless`, `effect_immunity`, `melee_strike`, the native `activate_all_buff_actions`.

## 4. Power notes

These numbers come from a dry run with `unit_design_lab.py tune --design V:/olden_port_work/unit_rebalance/ability_pass/scratch_homm3_dungeon.json`, with no write.

- Removing Pounce grows the Manticore line's hp: about 128 / 144 / 128 (base / Scorpicore / alt).
- Black Dragon hp grows to about 300 after losing Black Scales and Ancient Vigor. Red alt grows to about 354.
- Minotaur upgrades: about 75 / 80 hp (King / alt) after losing Alert, Gore, Thick Hide and Regeneration.
- Medusa alt hp about 46 (Lunge gone). Harpy line +2 hp. Infernal Troglodyte hp about 10 (Ambush is priced high and the reckless penalty is priced in).
- The faction median after tuning is 0.94x and every unit lands in band.

## 5. Risks

- **`overwatch` trigger.** Covering Fire queues on an attack, while Vigilant Eye queues on a move. The end-of-move dispatcher must not fire during the Beholder's own side's moves or mid-teleport.
- **Immovable vs push.** `effect_immunity movementNegative` blocks the root/slow buffs. It is unproven whether it blocks `push_unit_from_caster` and `swap_units`, which are mechanics, not buffs. If it does not, Immovable needs a plugin guard.
- **Cave-In obstacle lifetime.** `cave_in_obstacle` comes from a hero primal spell. Its duration and whether it can land on a corpse hex need checking.
- **`unacted_target`, `spent_counter`, `wall_slam`, `overwatch`** are plugin rules, so the damage forecast and the AI will not see them.
- **Venom Burst** detonates every `overTime_effect` on the target, including ones from other factions (poison, bleed). That is intended and emergent. Inferno's Burning is deliberately not tagged `overTime_effect`, so the two factions do not combine into one trick.
