# Tower (homm3_tower): ability pass draft, 2026-11-21

Trade axis: **Chassis** (`striker`: a multi-hit, ranged or large-HP body with a lean kit, so anything added to it pays off on every hit) versus **Specialist** (`ward`: a single-hit body that pays for a strong native kit of control, support and burst). Draft only. Nothing in the design table, keyword modules or plugin code has been changed.

The cuts sharpen the axis:

- **Chassis rows** lose their generic padding and keep one engine card.
- **Specialist rows** trade generic +Damage strikes for control and support that no other stack has.

## 1. Duplicates found

| Ability | Units | Why it is a duplicate or generic |
|---|---|---|
| Ball and Chain (`melee_strike` 1.0 + -1 Speed) | Gremlin, Gremlin alt | Identical, numbers included. |
| Three Speed debuffs | Ball and Chain / Chain Toss (-1), Golem alt Magnetic Field (-1 Speed, -1 Initiative), Golem alt Web keep (-2) | Three cards on one roster doing the same job, two of them on a single unit. |
| Three Defence debuffs | Gremlin alt Sabotage (-1), Golem alt Lodestone Fist (-3), Naga Queen Rending Blades and Six-Blade Flurry (-4) | The same rider repeated, with only the numbers changed. |
| `resist` padding | Master Gremlin Small Target, Gargoyle and Obsidian Gargoyle Stone Skin, Gargoyle alt Elemental Hide, Arch Mage Mana Ward, Spirit Form on all 3 Genies, Colossal on all 3 Giants | 10 generic damage-reduction rows. The Golem's Spell Damage Reduction is HoMM3 identity and stays. |
| Alert (`counters` 2) | Gargoyle alt, Giant alt | A generic second counterattack. |
| Tireless (`counters` 999) | Iron Golem | The same as Castle's Royal Griffin identity. |
| Swoop (`gallop` 0.05) | Obsidian Gargoyle | The per-hex bonus. |
| `shot` +x%, no counterattack | Arch Mage Arcane Bolt 1.5, Titan Thunderbolt 1.4 | The overused "+Damage, no counterattack" active, in shot form. |
| Six-Blade Flurry (`melee_strike` 1.6, no counterattack) | Naga Queen | The same pattern in melee form. |
| Lodestone Fist (`melee_strike` 1.3) | Golem alt | +Damage plus a Defence debuff. |
| Earthshaker (`swirl_strike`) | Giant alt | A plain whirlwind. |
| Repair x3 | Gremlin alt (10%, revives, any ally), Golem (40%, constructs), Iron Golem (60%, constructs) | These are kept. The Gremlin's Repair differs in kind (any ally, revives, charges) and the two Golem rows are one line identity, so they are not duplicates under the brief. |

## 2. Proposed kits

| Unit | Card | P/A | Card text | Build | Replaces |
|---|---|---|---|---|---|
| Gremlin | Ball and Chain | A 1/1 | Performs a Melee attack. The target has -1 Speed until the end of the next round. | `melee_strike` + `h3_kit_tower_chained_effect` | kept (base only) |
| Master Gremlin | Swarm Fire | P | Deals +10% Damage to a target for each other friendly stack that has attacked it this round, up to +30%. | NEW plugin rule `focus_fire` (percent 10, cap 30) | Small Target |
| Master Gremlin | Chain Toss | A 1/1 | Deals 75% basic attack Damage. The target has -1 Speed until the end of the next round. | `shot` + chained | kept. It is the ranged form of the Gremlin's melee line card. Rampart's Pinning Shot differs (50%, -2). |
| Gremlin alt | Sabotage | P | Basic attacks and counterattacks give the target -1 Defence until the end of the next round. | `on_hit_buff` loosened | kept. It is now the only Defence debuff in Tower. |
| Gremlin alt | Repair | A 2/- | (kept text) | `keep_ability` | kept |
| Gargoyle | Perch | P | When this creature Waits or Defends, it deals +30% Damage until the end of its next turn. | NEW keyword `on_wait_buff`: passive actions on `unit_wait` and `unit_skip` (condition `allegiance` ["self"]) buffing the unit itself with NEW `h3_kit_tower_perch_effect` (clone `sunlightCavalry_buff_1`, outAllDmgMod 0.3, maxDuration 2). The trigger shape is from `skill_formation_1_unit_bonus`. | Stone Skin |
| Gargoyle | Granite Dive | A 2/? | (kept text) | `keep_ability` | kept |
| Obsidian Gargoyle | Perch | P | When this creature Waits or Defends, it deals +40% Damage until the end of its next turn. | `on_wait_buff` 0.4 | Stone Skin, Swoop |
| Obsidian Gargoyle | No Retaliation | P | (vanilla) | `no_retaliation` | kept |
| Obsidian Gargoyle | Obsidian Drop | A 2/? | (kept text: slam for 85% and stun for 1 round) | `keep_ability` | kept |
| Gargoyle alt | Perch | P | When this creature Waits or Defends, it deals +30% Damage until the end of its next turn. | `on_wait_buff` 0.3 | Elemental Hide |
| Gargoyle alt | Granite Riposte | P | Counterattacks make the attacker deal -25% Damage until the end of the round. | `on_hit_buff` with a NEW `counterOnly` option + NEW buff `h3_kit_tower_granite_riposte_effect` (clone `hydra_debuff`, outAllDmgMod -0.25, maxDuration 1) | Alert |
| Gargoyle alt | Carapace | A 2/? | (kept text) | `keep_ability` | kept |
| Golem | Spell Damage Reduction | P | Takes -50% Magic Damage. | `resist` magic | kept (HoMM3 identity) |
| Golem | Repair | A 2/? | (kept) | `keep_ability` | kept |
| Iron Golem | Spell Damage Reduction | P | Takes -75% Magic Damage. | `resist` magic | kept (identity) |
| Iron Golem | Gathering Momentum | P | At the start of each round, gains +2 Attack until the end of the battle, up to +10. | NEW keyword `round_ramp`: a passive action on `start_round` (shape from the `assassin_upg_alt` start_round action) adding NEW `h3_kit_tower_momentum_effect` (offence 2, infinite), escalated to a cap through the existing `escalate` hook | Tireless |
| Iron Golem | Repair | A 2/? | (kept) | `keep_ability` | kept |
| Golem alt | Spell Damage Reduction | P | Takes -50% Magic Damage. | `resist` magic | kept |
| Golem alt | Lodestone Field | P | Adjacent enemy creatures always deal minimum Damage. | `stat_aura` radius 1, target enemy, stats `alwaysMinDmg` true (verified on the `black_dragon_upg_alt` aura, Dominating Presence) | Magnetic Field |
| Golem alt | Lodestone Pull | A 2/2 | Targets an adjacent empty hex and pulls the enemy creature directly behind it into that hex. Does not end this creature's turn. | NEW keyword `pull`: `giant_frog` ability 1 (Sticky Tongue: cast, `attack_reach_x1_x100_x100`, `push_unit` ["true","false"], actionCost 0, verified) | Web, Lodestone Fist |
| Mage | Battle Caster, Magic Channeler | P | unchanged | `tower_battle_caster`, `tower_channeler` 1 | kept (HoMM3 identity) |
| Arch Mage | Battle Caster, Magic Channeler (2) | P | unchanged | as now | kept |
| Arch Mage | Arcane Volley | P | Whenever the friendly hero casts a spell on an enemy creature, this creature also shoots that creature for 50% Damage. Once per round. | NEW plugin rule `spell_echo` (percent 50) on the Covering Fire / Avenger attack queue | Mana Ward, Arcane Bolt |
| Arch Mage | Silence | A 2/? | (kept text) | `keep_ability` | kept |
| Mage alt | Double Shot, Sharpshooter, Magic Channeler | P | unchanged | as now | kept (a lean Chassis) |
| Genie | Hatred of Efreet, Command: Reposition | P, A | unchanged | `hatred`, `keep_ability` | kept. Spirit Form is removed. |
| Master Genie | Hatred of Efreet, Wish, Refract and Reflect | P, A, A | unchanged | as now | kept. Spirit Form is removed. Wish (rotate) stays the signature. |
| Genie alt | Double Strike, Hatred of Efreet, Command: Switch Places | P, P, A | unchanged | as now | kept. Spirit Form is removed. |
| Naga | No Retaliation, Six Blades | P | unchanged | as now | kept (HoMM3 identity) |
| Naga Queen | No Retaliation, Six Blades | P | unchanged | as now | kept |
| Naga Queen | Serpent Dance | A 2/2 | Swaps places with an adjacent enemy creature. Does not end this creature's turn. | NEW keyword `swap_enemy`: `arbitrator_upg_alt` swap ability (`multitargetType` ordered, `numTargets` 2, `swap_units`, verified) with the first pick fixed to self, the second set to enemy, `distanceFromFirst` 1, and actionCost 0 | Rending Blades, Six-Blade Flurry |
| Naga alt | No Retaliation, Six Blades, Three-Headed Attack | P | unchanged | as now | kept (a lean Chassis) |
| Giant | Mind Immunity | P | Immune to Sleep, Silence and Berserk effects. | `card` | kept (HoMM3 identity). Colossal is removed. |
| Titan | Mind Immunity, Lightning Hurler, Hatred of Black Dragons | P | unchanged | as now | kept (identity). Colossal and Thunderbolt are removed: the Titan becomes the purest Chassis. |
| Giant alt | Mind Immunity, Hatred of Black Dragons | P | unchanged | as now | kept |
| Giant alt | Judgement | A 3/? | (kept: pure damage split across up to 4 enemies) | `keep_ability` | kept. Colossal, Alert and Earthshaker are removed. |

How each card changes play:

- **Master Gremlins** follow up on whatever the army already hit.
- **Gargoyles** reward holding back for a turn.
- **Gargoyle alt** blunts whoever hits it.
- **Iron Golem** grows into a late-battle threat.
- **Golem alt** drags one enemy in and smothers it with Lodestone Field.
- **Arch Mage** turns each hero spell into a follow-up shot.
- **Naga Queen** swaps an enemy's front-liner into your killing zone, or swaps itself out of a surround.

## 3. New mechanics needed

| Name | Kind | Spec | Native donor |
|---|---|---|---|
| `focus_fire` | plugin rule kind | Damage step: +percent for each distinct friendly stack (not the attacker) that dealt attack Damage to this target earlier in the round, up to cap. Per-round bookkeeping keyed by target id, reset in the round dispatcher. | `grudge` bookkeeping, scoped to the round |
| `on_wait_buff` | keyword | Two passive actions (`unit_wait`, `unit_skip`) with `allegiance` ["self"] that self-cast the given buff. | `skill_formation_1_unit_bonus` (verified unit_wait → self buff) |
| `h3_kit_tower_perch_effect` | buff | outAllDmgMod 0.3 (0.4 on the Obsidian row via a second buff or `escalate`), positive, maxDuration 2. | `sunlightCavalry_buff_1` |
| `on_hit_buff` `counterOnly` | keyword option | Writes the buff only on `counterAttacks`. | existing `on_hit_buff` |
| `h3_kit_tower_granite_riposte_effect` | buff | outAllDmgMod -0.25, negative, maxDuration 1. | `hydra_debuff` |
| `round_ramp` + `h3_kit_tower_momentum_effect` | keyword + buff | A `start_round` passive action that self-buffs with offence 2. It is stacked with `escalate` (already in the buff-add hook), capped at 5 stacks. | `assassin_upg_alt` start_round action (verified trigger) |
| `pull` | keyword | Clones `giant_frog` ability 1 unchanged, with Focus and cooldown from the entry. | `giant_frog` (verified) |
| `spell_echo` | plugin rule kind | On a friendly-hero spell resolving on an enemy unit, queues one free shot (percent damage multiplier) from each unit carrying the rule. It uses the Avenger / Covering Fire attack queue, at most once per round per unit. Needs a hero-cast hook: the native `cast_magic` trigger exists, but its spell target is not exposed to data. | `cast_magic` trigger (`sub_skill_tactics_3_unit_bonus`), Covering Fire runtime |
| `swap_enemy` | keyword | `arbitrator_upg_alt` swap ability, with the first target forced to the caster and the second target `enemy` at distance 1, and actionCost 0. | `arbitrator_upg_alt` (verified `swap_units`, ordered 2-target) |

Buffs that become unused: `h3_kit_tower_magnetized_effect` and `h3_kit_tower_rent_effect`. `h3_kit_tower_loosened_effect` stays on Sabotage. The Wish buffs stay.

## 4. Power notes

These numbers come from a scratch table at `V:/olden_port_work/unit_rebalance/ability_pass/scratch/homm3_tower.json` with estimated multipliers for the new cards. Body = the HP and Damage multiplier needed to get back to the current power.

| Unit | Now | Draft | Body |
|---|---|---|---|
| Giant alt | 0.97 | 0.82 | x1.18. It lost three cards; Judgement does carry it, so expect the tuner to land around +15%. It also fails the alternates gate against the Titan (0.96). |
| Naga Queen | 1.00 | 0.88 | x1.14. Serpent Dance and no-counter play are under-priced by the model. Alternates gate against the Naga alt (1.00). |
| Gremlin alt | 0.95 | 0.84 | x1.13. Alternates gate against the Master Gremlin (1.07). |
| Titan | 1.04 | 0.96 | x1.08 |
| Obsidian Gargoyle | 0.98 | 0.91 | x1.08 |
| Gargoyle alt | 1.05 | 0.99 | x1.06 |
| Iron Golem | 1.04 | 0.99 | x1.05 |
| Genie line | 0.87 / 0.93 / 1.03 | 0.84 / 0.91 / 1.00 | x1.03 (Spirit Form removed). The base Genie sits below the 0.85 band, so it needs at least that. |
| Giant base | 0.87 | 0.84 | x1.04 to re-enter the band |

- **Master Gremlin** rises to 1.07 with Swarm Fire. Shave about 5% off its body, or price Swarm Fire lower.
- **Gremlin pair:** the Master Gremlin at 1.07 against the Gremlin alt at 0.84 is the worst pair in this draft. Fix the bodies before anything else.

## 5. Risks

- **`spell_echo`** needs a hook on hero spell resolution that exposes the target. That hook does not exist in the runtime yet. This is the largest build in the Tower draft. Fallback: on any friendly hero cast, shoot the nearest enemy.
- **Lodestone Field** reuses Dominating Presence (`alwaysMinDmg` aura). Dungeon's HoMM3 Black Dragon may already carry it, so check the other faction draft before shipping, or the trick is shared.
- **Lodestone Pull** combined with Lodestone Field is a strong lockdown on one stack. AI pathing around pulled units has not been tested.
- **Serpent Dance** (`swap_units` on an enemy, distance 1) is a target-rule combination no shipped ability uses. Swapping a large unit (2 hexes) may fail silently.
- **Gathering Momentum** relies on `escalate` with a cap. The buff must survive dispels (`canDispel` false) or the card text must say it can be dispelled.
- **Perch** buffs that last "until the end of its next turn" use round durations. A unit that waits late in the round may lose the buff before it acts. Test the duration 2 choice.
