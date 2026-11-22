# Rampart (homm3_rampart): ability pass draft, 2026-11-21

Trade axis: **Striker** (high Initiative, on-hit riders, wants to be the stack that answers) versus **Ward** (durable bait that wants to be attacked). Draft only. Nothing in the design table, keyword modules or plugin code has been changed.

Rampart's signature cards stay: Covering Fire (Grand Elf), Shield Wall (Battle Dwarf), Grudge (Battlerager), Strangle (Dendroid Soldier), Diamond Scales (Diamond Dragon), Guardian Roar (Diamond Dragon), Runic Guard, Dazzle, Purifying Horn and Carry Off. They are unique on the roster. This pass mostly removes the generic cards stacked around them.

## 1. Duplicates found

| Ability | Units | Why it is a duplicate or generic |
|---|---|---|
| Evasive (`resist` Ranged -25%) | Wood Elf, Grand Elf, Wardancer, Pegasus | Four identical rows. |
| Dragon Scales / Adamant Hide (`resist` Ranged -25%, plus Melee on the Diamond) | Green, Gold and Diamond Dragon | The same number as Evasive. |
| Bark Skin (`resist` Melee -20%) | All three Dendroids | A generic damage-reduction passive. |
| Sturdy (`resist` basic -10%) | Dwarf, Battlerager | A generic damage-reduction passive. |
| `gallop` (Gallop, Swoop, Impale) | Centaur 5%, Centaur Captain 10%, Gold Pegasus 5%, Unicorn 5%, War Unicorn 10% | Five rows of the per-hex bonus. None of these creatures has it as a HoMM3 identity. |
| Alert (`counters` 2) | Battle Dwarf, War Unicorn, Pristine Unicorn, Diamond Dragon | A generic second counterattack. |
| Deep Roots (`counters` 999) | Dendroid Shaman | The same as Castle's Royal Griffin identity and Tower's Iron Golem. |
| Aimed Shot (`shot` +30%) | Wood Elf | The same as Castle's Archer Aimed Shot. |
| Dance of Blades (`swirl_strike`) | Wardancer | A plain whirlwind. |
| Lash Out (`reach_strike`) | Dendroid Soldier | A Long Thrust equivalent. |
| Crushing Blow (`melee_strike` 1.5) | Dendroid Soldier | +Damage and nothing else. |
| Fury of the Wood (`breath_strike` 1.3, return, no counterattack) | Gold Dragon | The "+x% no counterattack" pattern. |
| Dive (`dive` 1.3) | Gold Pegasus | The same as Castle's Griffin alt Battle Dive. |
| Wing Shelter (aura Ranged -15%) | Silver Pegasus | A generic resist aura. |
| Rivulet Retreat (keep) plus Carry Off | Silver Pegasus | Two repositioning tools on one unit. |
| Thicket (aura -1 Speed) | Dendroid Shaman | Speed debuffs are overused, and the aura slot is better spent elsewhere. |

## 2. Proposed kits

| Unit | Card | P/A | Card text | Build | Replaces |
|---|---|---|---|---|---|
| Centaur | Hunter's Eye | P | Deals +20% Damage to an enemy that has no other enemy creature adjacent to it. | NEW plugin rule `isolated_target` (percent 20) | Gallop |
| Centaur Captain | Hunter's Eye | P | Deals +30% Damage to an enemy that has no other enemy creature adjacent to it. | `isolated_target` (percent 30) | Gallop |
| Centaur Captain | Lead the Charge | A 1/2 | (unchanged) | `rally` | kept |
| Centaur Captain | Wheeling Charge | A 1/1 | Performs a Melee attack, then returns to its original position. | `melee_strike` return | kept. It is now the only strike-and-return in Rampart. |
| Centaur Ranger | Skirmisher, Pinning Shot | P, A 1/1 | unchanged | unchanged | kept |
| Dwarf | Magic Resistance | P | Takes -20% Magic Damage. | `resist` magic -0.2 | kept (HoMM3 identity) |
| Battle Dwarf | Magic Resistance | P | Takes -40% Magic Damage. | `resist` magic -0.4 | kept (identity) |
| Battle Dwarf | Shield Wall | P | Takes -10% Damage for each adjacent friendly creature, up to -30%. | runtime `adjacent_ally_ward` | kept |
| Battle Dwarf | Runic Guard | A 2/2 | (unchanged) | `self_buff` | kept |
| Battlerager | Magic Resistance | P | Takes -20% Magic Damage. | `resist` | kept |
| Battlerager | Grudge | P | (unchanged) | runtime `grudge` | kept |
| Battlerager | Reckless Swing | A 1/1 | (unchanged) | `melee_strike` + self debuff | kept. The +Damage comes with a real cost, so it is not the generic pattern. |
| Wood Elf | Forest Ambush | P | Ranged attacks deal +30% Damage to enemies that have not acted yet this round. | NEW plugin rule `target_not_acted` (percent 30) | Evasive, Aimed Shot |
| Grand Elf | Double Shot, Sharpshooter | P | (vanilla) | `double_strike`, `sharpshooter` | kept (Double Shot is HoMM3 identity) |
| Grand Elf | Covering Fire | A 2/2 | (unchanged) | `self_buff` runtime covering_fire | kept |
| Wardancer | Double Strike | P | (vanilla) | `double_strike` melee | kept |
| Wardancer | Leaf Storm | A 2/2 | Moves to any hex and deals basic attack Damage to every adjacent enemy. | `landing` focus 2, cd 2, enemiesOnly true, push false (donor `black_dragon_upg_alt` ability 1) | Evasive, Dance of Blades |
| Pegasus | Magic Damper | P | Enemy hero's spells cost +1 mana. This effect does not stack; only the strongest one is active. | `magic_damper` 1 | kept (HoMM3 identity) |
| Silver Pegasus | Magic Damper | P | Enemy hero's spells cost +2 mana. | `magic_damper` 2 | kept |
| Silver Pegasus | Spell Sentinel | P | Whenever the enemy hero casts a spell, this creature gains 1 Focus. | NEW keyword `focus_on_enemy_cast`: a passive action on trigger `cast_magic`, condition `allegiance` ["enemy"], self mechanic `add_energy` ["1"] (trigger shape from `sub_skill_tactics_3_unit_bonus`, add_energy from `olgoi_upg`) | Wing Shelter |
| Silver Pegasus | Carry Off | A 2/2 | Select this creature, then a friendly creature within 4 hexes. The two swap places. | `swap` | kept. Spell Sentinel feeds it. |
| Gold Pegasus | Magic Damper | P | Enemy hero's spells cost +2 mana. | `magic_damper` 2 | kept |
| Gold Pegasus | No Retaliation | P | (vanilla) | `no_retaliation` | kept |
| Gold Pegasus | Dispelling Hooves | P | Basic attacks remove one positive effect from the target. | NEW keyword `dispel_on_hit`: target mechanic `dispel` with count 1, positive only (dispel values from `lightweaver_upg` ability 1, which `mass_dispel` already reads), on the default attack | Swoop, Dive |
| Dendroid Guard | Binding | P | Basic attacks and counterattacks root the target. It cannot move until the end of the next round. | `on_hit_buff` ent_root | kept (HoMM3 identity) |
| Dendroid Soldier | Binding | P | as above | `on_hit_buff` | kept |
| Dendroid Soldier | Strangle | P | Deals +30% Damage to rooted enemies. | runtime `damage_vs_buff` | kept |
| Dendroid Soldier | Overgrowth | A 2/2 | Roots every enemy adjacent to this creature until the end of the next round. Does not end this creature's turn. | NEW keyword `area_debuff_self`: cast with pattern `attack_rumble_without_self_x100_x100` (or swirl_x1), damageTarget none, buff ent_root duration 2, actionCost 0 (envelope from `sunlight_cavalry_upg` ability 0) | Bark Skin, Lash Out, Crushing Blow |
| Dendroid Shaman | Binding | P | as above | `on_hit_buff` | kept |
| Dendroid Shaman | Living Cover | P | Adjacent friendly creatures always take minimum Damage. | `stat_aura` radius 1, target ally, stats `alwaysTakeMinDmg` true (verified on the `ent_upg` aura) | Bark Skin, Deep Roots, Thicket |
| Dendroid Shaman | Sap Mend | A 2/2 | (unchanged) | `revive` | kept |
| Unicorn | Aura of Resistance | P | This creature and adjacent friendly creatures take -20% Magic Damage. | `aura` magic | kept (HoMM3 identity) |
| Unicorn | Blinding Strike | A 3/3 | (unchanged) | `melee_strike` + unicorn_blind | kept (HoMM3 identity: blinding, with chance turned into Focus) |
| War Unicorn | Aura of Resistance | P | as Unicorn | `aura` | kept |
| War Unicorn | Radiant Horn | P | Basic attacks and counterattacks give the target -2 Initiative until the end of the next round. | `on_hit_buff` with NEW buff `h3_kit_rampart_radiant_effect` (clone `hydra_debuff`, initiative -2, the idea of `medusa` Marble Arrows) | Impale, Alert |
| War Unicorn | Blinding Strike | A 2/3 | (unchanged) | `melee_strike` | kept |
| Pristine Unicorn | Radiant Armor (keep), Aura of Resistance r2, Dazzle, Purifying Horn | mixed | unchanged | unchanged | kept. Alert is removed. |
| Green Dragon | Breath, Spell Immunity III | P | unchanged | `card`, `spell_immunity` 3 | kept (HoMM3 identity). Dragon Scales is removed. |
| Gold Dragon | Breath, Spell Immunity IV, No Retaliation, Fearless | P | unchanged | as now | kept |
| Gold Dragon | Dragonfire | A 3/3 | Performs a breath attack. Every creature it hits burns: it takes 15% of this attack's Damage as Magic Damage at the start of each of its next two turns. | NEW keyword `breath_dot`: the unit's own breath default attack as an ability (the `breath_strike` builder without return or counter changes) + NEW buff `h3_kit_rampart_dragonfire_effect` cloned from `frog_poison` (stackable start-of-turn Magic Damage, duration 2). Its value is set from the attacker's damage by a small NEW plugin rule `scaled_dot` or a fixed per-stack value. | Dragon Scales, Fury of the Wood |
| Diamond Dragon | Breath, Spell Immunity III | P | unchanged | as now | kept |
| Diamond Dragon | Diamond Scales | P | No single hit can deal more than 20% of this stack's full Health. | runtime `hit_cap` | kept |
| Diamond Dragon | Guardian Roar | A 3/3 | (unchanged) | `self_buff` taunt | kept. It is the only taunt among Castle, Rampart and Tower. |

How each card changes play:

- **Centaurs** pick off stragglers.
- **Wood Elves** fire before the enemy moves, which rewards Rampart's Initiative.
- **Wardancers** jump into a cluster.
- **Silver Pegasus** banks Focus from enemy spells and spends it on Carry Off.
- **Gold Pegasus** strips buffs.
- **Dendroid Soldier** roots a ring of enemies, then Strangles them.
- **Dendroid Shaman** is a living shield for whatever stands beside it.
- **War Unicorn** pushes enemies down the turn order.
- **Gold Dragon** leaves lingering burns.
- **Diamond Dragon** stays the bait.

## 3. New mechanics needed

| Name | Kind | Spec | Native donor |
|---|---|---|---|
| `isolated_target` | plugin rule kind | Damage step, attacker side: +percent when no living stack allied to the target occupies a hex adjacent to the target. It reuses the `adjacent_ally_ward` neighbour scan, run on the target with the target's own allegiance. | `adjacent_ally_ward` code |
| `target_not_acted` | plugin rule kind | Damage step: +percent when the target has not yet taken an action in the current round. This is the same per-unit "acted this round" flag the Set Pikes build already needs, read on the target instead of the owner. Waiting counts as not acted. | Set Pikes action tracking (owner lane) |
| `focus_on_enemy_cast` | keyword | Passive action: `trigger: cast_magic`, `triggerConditions: [{checkFunction: allegiance, values: [enemy]}]`, self cast with the `add_energy` mechanic. Pure native data. | `sub_skill_tactics_3_unit_bonus` (verified cast_magic + enemy), `olgoi_upg` add_energy (verified) |
| `dispel_on_hit` | keyword | Adds the dispel target mechanic (positive effects, limit 1) to the default attack dealer. The limit parameter has to be confirmed against the `lightweaver_upg` ability 1 values. If dispel cannot be limited to 1, the card text becomes "removes all positive effects" and the body shrinks. | `lightweaver_upg` ability 1 |
| `area_debuff_self` | keyword | A free-action cast centred on the unit, with a no-self ring pattern, no Damage and a buff on enemies. | `sunlight_cavalry_upg` ability 0 envelope; pattern `attack_rumble_without_self_x100_x100` or `attack_swirl_x1_x100` |
| `breath_dot` + `h3_kit_rampart_dragonfire_effect` | keyword + buff | A breath ability whose dealer applies a cloned `frog_poison` buff to every target. If no per-hit scaling is wanted, set the poison value per stack with `escalate`. | `giant_frog` (verified `frog_poison`, duration 2) |
| `scaled_dot` (optional) | plugin rule kind | Sets the burn value to percent of the damage the applying hit dealt. It can be skipped if a flat value is used. | buff-add hook |
| `h3_kit_rampart_radiant_effect` | buff | A clone of `hydra_debuff` with initiative -2, tagged negative, maxDuration 2. | `hydra_debuff` |

No buff rows become unused. Wing Shelter and Thicket were aura entries, not buffs. Dazzle and Pinned stay in use.

## 4. Power notes

These numbers come from a scratch table at `V:/olden_port_work/unit_rebalance/ability_pass/scratch/homm3_rampart.json` with estimated multipliers for the new cards. Body = the HP and Damage multiplier needed to get back to the current power.

| Unit | Now | Draft | Body |
|---|---|---|---|
| Dendroid Soldier | 1.06 | 0.85 | x1.20 (it lost two actives and Bark Skin; Overgrowth control is under-priced by the model) |
| War Unicorn | 0.99 | 0.82 | x1.18. It also fails the alternates gate against Pristine (0.94), so give the War Unicorn the body first. |
| Diamond Dragon | 1.02 | 0.89 | x1.12 (Adamant Hide and Alert are gone; Diamond Scales still caps burst) |
| Gold Pegasus | 1.02 | 0.90 | x1.12 |
| Dendroid Shaman | 1.02 | 0.92 | x1.08. Living Cover's value to the army is invisible to the model; lean low. |
| Wood Elf | 0.90 | 0.83 | x1.08 |
| Dendroid Guard | 0.91 | 0.86 | x1.06 |
| Battle Dwarf | 1.02 | 0.96 | x1.06 |
| Unicorn | 1.00 | 0.94 | x1.06 |
| Pristine Unicorn | 1.00 | 0.94 | x1.06 |
| Dwarf | 0.92 | 0.88 | x1.05 |

All other Rampart units stay within ±0.04. The Centaur Captain rises to 1.05; trim its HP by one point.

## 5. Risks

- **`target_not_acted`** depends on the action-tracking flag being built for Set Pikes. If that flag lives in a Castle-only code path, it has to be generalized.
- **`dispel_on_hit`:** whether a dispel can be limited to one effect is unverified. Vanilla dispels all.
- **Overgrowth** as a free action: rooting a ring and then attacking a rooted target with Strangle in the same turn may be too strong. Fallback: make it end the turn.
- **Living Cover** combined with Shield Wall Battle Dwarves next to the Shaman may make a near-unkillable block. The power model cannot price that.
- **Spell Sentinel:** the `cast_magic` trigger is proven only on a hero sub-skill buff, not on a unit passive.
- **Dragonfire:** stacking `frog_poison` clones from several sources may interact with poison immunities (embodiments, constructs). Check the effect tags.
- **Leaf Storm** reuses the `landing` keyword that one other faction row already ships. The trick is not new to the roster, only to Rampart; a reviewer may count it as shared.
