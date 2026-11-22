# Castle (homm3_castle): ability pass draft, 2026-11-21

Trade axis: **Cleave** (`striker`: shaped attacks that pay off against many small or bunched stacks) versus **Lance** (`ward`: tools that pay off against one big stack). Draft only. Nothing in the design table, keyword modules or plugin code has been changed.

## Fixed decisions (being built separately by the owner)

- **Set Pikes**, on the Pikeman, Halberdier and Glaivier: the counterattack strikes first only until the stack acts in the round. Waiting and Defending do not count as acting. Built as `castle_set_pikes`.
- **Halberdier:** Sweeping Halberd is removed and Reaping Arc stays.
- **Glaivier:** Long Thrust is replaced by **Guillotine**, built as `castle_guillotine` (`magic_decimate_effect`, `magic_pure`).

The rest of this draft is designed around these three. No other Castle card has a first strike, a 2-hex thrust or Pure Damage.

## 1. Duplicates found

| Ability | Units | Why it is a duplicate or generic |
|---|---|---|
| `castle_cleave` swipe ("also hit the two enemies to the sides") | Halberdier (removed), Royal Griffin Rending Talons, Swordsman alt Wide Sweep, Champion alt Mounted Sweep, Archangel alt Flaming Sweep (100%) | The same shape on 5 rows, and identical except for one number. |
| Plain whirlwind (`swirl_strike` / swirl `castle_strike`) | Halberdier Reaping Arc (kept, fixed), Royal Griffin Wing Storm, Swordsman alt Whirling Guard, Archangel alt Heavenly Fire | Four identical "strike every adjacent enemy, no counterattack" actives. |
| `castle_strike` +x%, no counterattack | Crusader Smite 1.5, Angel Smite 1.3, Archangel Smite 1.5, Champion Ride Through 1.3 | One overused pattern under one name, used three times. |
| `reach_strike` | Glaivier Long Thrust (fixed: replaced), Crusader Lunge, Champion Lance Reach | Long Thrust equivalents. |
| `armorPen` passive | Glaivier Impale 30%, Champion Couched Lance 25%, Archangel Sword of Judgement 25% | Three of the same Defence-ignoring stat. |
| `counters` 2 (Alert) | Griffin, Griffin alt (both HoMM3 identity), Swordsman alt, Champion alt | Generic on the last two. |
| `gallop` 0.05 | Cavalier, Champion alt (Jousting identity), Griffin alt Stoop | Stoop is the generic per-hex bonus. |
| `shot` +30% | Archer and Marksman Aimed Shot, Monk Rebuke | Identical "+30% shot". |
| Rumble shot x1 100/50 | Archer alt Scatter Shot, Zealot Pillar of Flame (plus Searing Light at 25%) | The same area shot on two lines. |
| `ignoreShootingBlock` | Archer alt Point Blank, Monk alt Holy Fire | The same passive twice. |
| Holy Fire +10% Ranged Damage | All three Monks | A bland stat card. |
| `resist` basic -15% | Swordsman, Swordsman alt | A generic damage-reduction passive. |
| Two "takes more Damage" shots | Marksman Marked Target (+20% Damage taken), Monk alt Judgement (-4 Defence) | Functionally close setups. |

## 2. Proposed kits

P = passive. A = active, written as Focus/cooldown.

| Unit | Card | P/A | Card text | Build | Replaces |
|---|---|---|---|---|---|
| Pikeman | Set Pikes | P | (fixed) | `castle_set_pikes` | fixed |
| Pikeman | Braced Pikes | P | Takes -25% Damage from creatures whose Damage grows with the distance they move before attacking. | `brace` -0.25 | kept |
| Halberdier | Set Pikes, Braced Pikes | P | as Pikeman | as Pikeman | fixed / kept |
| Halberdier | Reaping Arc | A 1/1 | Attacks an enemy and strikes every other adjacent enemy for 50% Damage. Enemies do not counterattack. | `castle_strike` swirl x100_x50 | fixed, kept |
| Glaivier | Set Pikes, Braced Pikes | P | as Pikeman | as Pikeman | fixed / kept |
| Glaivier | Impale | P | Attacks ignore 30% of the target's Defence. | `castle_stat` armorPen 0.3 | kept. It is now Castle's only armorPen card. |
| Glaivier | Guillotine | A 1/1 | (fixed) | `castle_guillotine` | fixed |
| Archer | Stand Ground | P | Ranged attacks deal +25% Damage if this creature did not move during its previous turn. | NEW plugin rule `stood_ground` (percent 25) | Aimed Shot |
| Marksman | Double Shot | P | (vanilla text) | `double_strike` shoot | kept (HoMM3 identity) |
| Marksman | Marked Target | A 1/2 | Deals 50% basic attack Damage. The target takes +20% Damage until the end of the next round. | `castle_shot` + `h3_kit_castle_marked_effect` | kept. It is now Castle's only "takes more Damage" setup. |
| Archer alt | Sharpshooter, Point Blank, Scatter Shot | P, P, A 1/1 | unchanged | unchanged | kept. These are now Castle's only ignoreShootingBlock and its only rumble shot. |
| Griffin | Alert | P | Can counterattack up to twice per round. | `counters` 2 | kept (HoMM3 identity) |
| Royal Griffin | Unlimited Retaliation | P | Can counterattack unlimited times per round. | `counters` 999 | kept (HoMM3 identity) |
| Royal Griffin | Talon Riposte | P | Counterattacks also hit the two enemies to the sides of the attacker for 50% Damage. Basic attacks do not. | `castle_cleave` with a new `buckets: ["counterAttacks"]` option (swipe x100_x50 on the counter only) | Rending Talons |
| Royal Griffin | Flock Fighter | P | Deals +10% Damage for each enemy adjacent to this creature, up to +30%. | NEW plugin rule `crowd_fury` (percent 10, cap 30) | Wing Storm |
| Griffin alt | Alert | P | Can counterattack up to twice per round. | `counters` 2 | kept (griffin line identity) |
| Griffin alt | Pinning Talons | P | Basic attacks and counterattacks remove 1 of the target's counterattacks for this round. | `on_hit_buff`-style target mechanic `reduce_counters` ["1"] (donor `unfrozen_cultist_upg` ability 2) on the default and counter attacks | Stoop |
| Griffin alt | Battle Dive | A 2/2 | Flies to any enemy on the battlefield and strikes it for +50% Damage. The enemy does not counterattack. | `dive` 1.5 range 99 | kept. Rampart's Gold Pegasus loses its Dive, so this is the only dive among Castle, Rampart and Tower. |
| Swordsman | Hold Fast | P | Takes -25% Damage from the first attack made against it each round. | NEW plugin rule `first_hit_ward` (percent 25) | Guard Formation |
| Crusader | Double Strike | P | (vanilla text) | `double_strike` melee | kept (HoMM3 identity) |
| Crusader | Challenge | A 2/2 | Performs a Melee attack. Until the end of the next round, the target deals -50% Damage to creatures other than this one. | `castle_strike` (counter true) + NEW buff `h3_kit_castle_challenged_effect` (clone `hydra_debuff`, marker only) + NEW plugin rule `duel_mark` (percent 50) | Lunge, Smite |
| Swordsman alt | Hold Fast | P | Takes -15% Damage from the first attack made against it each round. | `first_hit_ward` (percent 15) | Guard Formation, Alert |
| Swordsman alt | Follow Through | P | When this creature's attack destroys an enemy stack, it can act again this round. Once per round. | NEW keyword `kill_extra_action`: the `godslayer_upg_alt` passive (`unit_died` + `allegiance_both` [self, enemy] + `is_active_unit` → `add_action_points`, `maxAddedApPerRound` 1) | Wide Sweep, Whirling Guard |
| Monk | Retribution | P | Deals +25% Damage to enemies that damaged a friendly creature this round. | NEW plugin rule `retribution` (percent 25) | Holy Fire, Rebuke |
| Zealot | Duelist | P | Receives no penalty in Melee range, dealing full Damage. | `skirmisher` | kept (HoMM3 identity) |
| Zealot | Retribution | P | Deals +25% Damage to enemies that damaged a friendly creature this round. | `retribution` (percent 25) | Holy Fire, Searing Light. The card is shared across the Monk line as line identity. |
| Zealot | Brand of Faith | A 2/2 | Performs a Ranged attack. Until the end of the next round, whenever the target takes Damage from an attack, every enemy adjacent to it takes 25% of that Damage. | `castle_shot` + NEW buff `h3_kit_castle_brand_effect` (clone `crossbowman_debuff`) + NEW plugin rule `brand_splash` (percent 25) | Pillar of Flame |
| Monk alt | Humble the Mighty | P | Deals +25% Damage to stacks that have more creatures than this one. | NEW plugin rule `outnumbered` (percent 25) | Holy Fire, Sharpshooter, Judgement |
| Monk alt | Benediction | A 2/2 | One friendly creature gains +4 Attack and +4 Defence until the end of the next round. | `castle_ally_buff` | kept |
| Cavalier | Jousting | P | Moving before an attack increases Damage by 5% per hex moved. | `gallop` 0.05 | kept (HoMM3 identity) |
| Cavalier | Cavalry Press | A 2/? | (kept text) | `keep_ability` | kept |
| Champion | Jousting | P | Moving before an attack increases Damage by 10% per hex moved. | `gallop` 0.1 | kept (identity) |
| Champion | Unhorse | P | After moving 4 or more hexes before a Melee attack, the target cannot counterattack. | NEW plugin rule `charge_no_counter` (hexes 4) | Couched Lance, Ride Through |
| Champion | Cavalry Press | A 2/2 | Charges for 75% Damage and gives the target -3 Attack and -3 Defence for 2 rounds. | Cavalier's ability cloned into the Champion row (NEW keyword `castle_clone_ability`, or carry it through the rebuild) | Lance Reach |
| Champion alt | Jousting | P | Moving before an attack increases Damage by 5% per hex moved. | `gallop` 0.05 | kept |
| Champion alt | Scatter the Ranks | P | Basic attacks push the target 1 hex away, if possible. | NEW keyword `push_on_hit`: target mechanic `push_unit_from_caster` ["false"] (donor `minos_selfbuff`, Minotaur's Onslaught) on the default attack | Alert, Mounted Sweep |
| Champion alt | Trample | A 2/2 | Attacks an enemy and every enemy within two hexes in a line behind it for full Damage. Enemies do not counterattack. | `castle_strike` reach_x2 | kept. It is the only line strike, and its shape is its identity. |
| Champion alt | Command: Fear | A 2/? | (kept text) | `keep_ability` | kept |
| Angel | Aura of Valor, Hatred of Devils | P | unchanged | `army_stat`, `hatred` | kept (HoMM3 identity) |
| Angel | Descend | A 2/3 | Flies to any free hex on the battlefield. Does not end this creature's turn. | NEW keyword `free_teleport`: the `aqualotl_upg` ability 3 (Rivulet Retreat, teleport, actionCost 0) with range 99. Rampart's Silver Pegasus loses its copy. | Smite |
| Archangel | Aura of Valor, Fearless, Hatred of Devils | P | unchanged | as now | kept |
| Archangel | Resurrection | A 3/3 | (unchanged) | `revive` | kept (HoMM3 identity) |
| Archangel | Vengeance of Heaven | P | Whenever a friendly creature stack is destroyed, this creature gains +4 Attack until the end of the battle. | NEW keyword `ally_death_buff`: a `unit_died` passive with condition `allegiance` ["ally"], self buff NEW `h3_kit_castle_vengeance_effect` (clone `sunlightCavalry_buff_1`, offence 4, infinite) added through the `escalate` hook so it stacks | Sword of Judgement, Smite |
| Archangel alt | Aura of Valor, Fearless, Hatred of Devils | P | unchanged | as now | kept |
| Archangel alt | Flaming Sword | P | Basic attacks and counterattacks also hit the enemy directly behind the target for 50% Damage. | `castle_cleave` pattern `attack_reach_x1_x100_x50` (already in MELEE_SHAPES) | Flaming Sweep |
| Archangel alt | Wrathful Chalice | A 3/3 | Removes all positive effects from enemies within a 1-hex radius of the chosen hex and applies them to this creature. | NEW keyword `steal_area`: `angel_upg` ability 3 (Devouring Chalice, `steal_buffs` ["true"]) | Heavenly Fire |
| Archangel alt | Reality Distortion | A 3/? | (kept text) | `keep_ability` | kept |

How each card changes play:

- **Archer** stays put to keep its bonus.
- **Royal Griffin** wants to be surrounded.
- **Griffin alt** strips counterattacks off a big stack so the rest of the army can hit it freely.
- **Crusader** pins the enemy's best stack onto itself.
- **Swordsman alt** hunts small stacks to chain its turns.
- **Monks** punish whoever just hit your line, or soften bunched enemies with Brand of Faith. Humble the Mighty goes after the biggest stack.
- **Champion** needs a long run-up to get Unhorse.
- **Champion alt** breaks enemy formations.
- **Angel** projects threat anywhere on the battlefield.
- **Archangel** turns your losses into Attack.

## 3. New mechanics needed

| Name | Kind | Spec | Native donor |
|---|---|---|---|
| `stood_ground` | plugin rule kind | Damage step, attacker side. The bonus applies when the attack is a shot and the unit's previous turn ended without a move. Track this with the unit_end_move and action dispatchers: set `moved` on any move and clear it at the start of the unit's turn. It counts as true at battle start. | none (plugin) |
| `crowd_fury` | plugin rule kind | Damage step, attacker side: +percent for each living enemy stack on a hex adjacent to the attacker, up to cap. It is the mirror of `adjacent_ally_ward` (same neighbour scan, enemies instead of allies), and it applies to counterattacks too. | `adjacent_ally_ward` code |
| `first_hit_ward` | plugin rule kind | Damage step, defender side: -percent on the first damaging attack that targets this unit in each round. Store a per-unit flag and reset it in the round dispatcher. Splash hits do not consume the flag. | round dispatcher (Warcry runtime) |
| `duel_mark` | plugin rule kind + marker buff | Damage step, attacker side: if the attacker carries `h3_kit_castle_challenged_effect` and the target is not the stack that applied the buff, Damage takes -percent. The caster id is recorded when the buff is added, through the buff-add hook. | buff-add hook |
| `retribution` | plugin rule kind | Damage step: +percent when the target dealt damage to any unit on the attacker's side earlier in the current round. Use a per-round set of attacker ids (the same bookkeeping as `grudge`, scoped to a side and reset every round). | `grudge` code |
| `brand_splash` | plugin rule kind + buff | When a unit carrying `h3_kit_castle_brand_effect` takes attack Damage, the rule queues percent of the final Damage as Pure Damage to each enemy-of-caster stack adjacent to it. It does not recurse on its own splash. | attack queue / Avenger damage path |
| `outnumbered` | plugin rule kind | Damage step: +percent when the target stack's creature count is above the attacker's. | none |
| `charge_no_counter` | plugin rule kind | At attack commit, if the attacker moved at least `hexes` hexes this turn, disable the counter for this attack (the `disable_counter` sequence effect, or set triggerCounter false on the live dealer). | `damagePerHex` path distance; ability commit hook |
| `kill_extra_action` | keyword | Clones the `godslayer_upg_alt` passive: trigger `unit_died`, conditions `allegiance_both` [self, enemy] and `is_active_unit`, mechanic `add_action_points`, plus stat `maxAddedApPerRound` 1. | `godslayer_upg_alt` (verified) |
| `push_on_hit` | keyword | Adds target mechanic `push_unit_from_caster` ["false"] to the default attack dealer. | `minos_selfbuff` (verified) |
| `free_teleport` | keyword | `aqualotl_upg` ability 3 (Rivulet Retreat: teleport, actionCost 0) with its range set from the entry. | `aqualotl_upg` (verified, also the Silver Pegasus keep) |
| `ally_death_buff` | keyword | A passive action on `unit_died` with `allegiance` ["ally"] that buffs the unit itself. The stacking buff is escalated through the existing `escalate` hook. | `godslayer_upg_alt` unit_died shape |
| `steal_area` | keyword | `angel_upg` ability 3: castTarget all, hexOrObject, affect enemy, `steal_buffs` ["true"]. | `angel_upg` (verified) |
| `reduce_counters` on hit | keyword | A target mechanic `reduce_counters` ["1"] on the default and counter dealers. | `unfrozen_cultist_upg` ability 2 (verified) |
| `castle_cleave` `buckets` | keyword option | Applies the pattern only to the listed attack buckets. The docstring mentions this already; it needs a counter-only mode. | existing |
| Champion Cavalry Press | keyword | Copies the Cavalier's kept ability into the Champion row, or adds a `from` field to `keep_ability`. | `h3_cavalier` row |

New buffs:

- `h3_kit_castle_challenged_effect` (clone of `hydra_debuff`, no stats, negative)
- `h3_kit_castle_brand_effect` (clone of `crossbowman_debuff`, no stats, 2 rounds)
- `h3_kit_castle_vengeance_effect` (offence 4, infinite)

The Judged buff and the Holy Fire cards become unused.

## 4. Power notes

These numbers come from a scratch table at `V:/olden_port_work/unit_rebalance/ability_pass/scratch/homm3_castle.json`, built by `build_scratch.py`. New cards are priced as `card` entries with estimated `offMult`/`toughMult`. Body = the HP and Damage multiplier needed to get back to the current power.

| Unit | Now | Draft | Body |
|---|---|---|---|
| Archer | 0.89 | 0.83 | x1.07 |
| Royal Griffin | 1.02 | 0.95 | x1.07 |
| Swordsman alt | 1.02 | 0.81 | x1.25 (the body has room: Damage 6-9 is low for T4) |
| Monk alt | 0.94 | 0.85 | x1.10 |
| Archangel | 1.01 | 0.86 | x1.15 |
| Archangel alt | 0.93 | 0.83 | x1.12 |
| Champion alt | 0.99 | 0.93 | x1.06 |

- **Unchanged or about the same:** Crusader, Marksman, Zealot, Champion and Angel stay within ±0.03.
- **Model blind spots:** the model cannot see Challenge, Pinning Talons, Unhorse or Descend, so the bodies of those units are probably slightly generous.
- **Swordsman pair (alternates gate):** run `tune` on the Swordsman alt first, then re-check the pair (0.99 vs 0.81 in the scratch run).
- **Monk pair:** the same applies to the Monk upgrade and Monk alt.
- **Champion kit size:** the Champion needs 3 cards to stay above the base kit size of 2. Cavalry Press covers that.

## 5. Risks

- **Unproven plugin rules:** `stood_ground`, `first_hit_ward`, `retribution` and `charge_no_counter` all need new per-unit state in the dispatchers. "Moved this turn" and "hexes moved" have not yet been read anywhere in the runtime.
- **`charge_no_counter`:** suppressing a counter from the plugin, rather than from the damage step, needs the ability commit hook. This is the biggest unknown.
- **`brand_splash`** deals damage from inside the damage step. Re-entrancy (a splash triggering another splash, Avenger, or Covering Fire) has to be guarded.
- **Talon Riposte and Unlimited Retaliation** together can spike against swarms. Watch AI threat values.
- **Follow Through** (`add_action_points`) has only been proven on vanilla Godslayer. It may let the Swordsman alt chain turns with Double Strike sources from heroes.
- **Wrathful Chalice and Vengeance of Heaven** stack buffs on one unit. Check that their buffs are not mirrored by Angel-family Forging-Perfection style rows.
- **Card readability:** "-50% Damage to creatures other than this one" may be hard to read in the forecast. The forecast cannot show plugin rules.
