# Stronghold: ability variety draft (2026-11-21)

Draft only. Nothing here is built. Trade axis (unchanged): **Opener** (striker) reaches melee or acts in place so an attack chain starts and never pauses, versus **Finisher** (ward), slower and harder-hitting, worth most late in a round. No card reads Warcry or any faction tag. Every Finisher payoff below reads a battlefield fact that any army produces.

## 1. Duplicates found

| Ability | Units | Why it is a duplicate or generic |
|---|---|---|
| 5% Damage per hex (`gallop` 0.05/0.10): Scurry, Pounce, Tusk Charge, Swoop | Goblin alt; Wolf Rider, Wolf Raider, boar alt (0.10); Roc, Thunderbird, Roc alt | 7 of 21 rows. The owner's named example. One number on one trigger across four lines. |
| Armor Rend (`stronghold_armor_rend` 15 to 50%): Bone Breaker, Lightning Talons, Heavy Boulders, Armor Rend | Ogre alt, Thunderbird, all 3 Cyclops, all 3 Behemoths | 8 rows. The owner's named example. It is the Behemoth's HoMM3 identity and nobody else's. |
| Alert (`counters` 2) | Hobgoblin, Orc alt, Ancient Behemoth | Generic second counterattack. Nothing Stronghold-flavoured about it. |
| "+x% strike" actives: Savage Blow, Berserk Swing, Crushing Blow, Lightning Strike, Devastating Blow, Boulder Smash x2 | Hobgoblin, Orc alt, Ogre alt, Thunderbird, Ancient Behemoth, Cyclops, Cyclops King | 7 actives that are a damage multiplier, sometimes with no counterattack. |
| Thick Hide / Wing Buffet / Shaman's Ward / Ethereal (`resist`) | boar alt, 3 Ogres, 3 Rocs, Ogre Mage, Behemoth alt | 10 generic damage-reduction rows. |
| Dive anywhere (`dive` 99): Stoop, Spectral Pounce | Roc alt, Behemoth alt | Same trick on two strikers in one faction. |
| Double Strike | Wolf Raider, Roc alt | The Wolf Raider's HoMM3 identity, copied onto the Roc alt. |
| Unstoppable | Ogre alt, 3 Behemoths | Behemoth line identity, copied onto the Ogre alt. |
| Stat rallies and auras: Chieftain's Orders (+2 Attack), Battle Chant (+1 Initiative) | Orc Chieftain, Ogre Mage | Small generic buffs that do not change positioning or sequencing. |

## 2. Proposed kits

P = passive. A = active (Focus / cooldown in rounds). "Kept" = the card is unchanged.

| Unit | Card | P / A | Card text | How it is built | Replaces |
|---|---|---|---|---|---|
| Goblin | Safety in Numbers | P | Takes -5% Damage for each adjacent friendly creature, up to -15%. | kept (`runtime adjacent_ally_ward` 5/15) | - |
| Hobgoblin (Finisher) | Safety in Numbers | P | (as Goblin) | kept | - |
| | Pile On | P | Deals +25% Damage to an enemy that has already taken Damage this round. | new plugin rule `struck_this_round` percent 25 | Alert, Savage Blow |
| Goblin alt (Opener) | Safety in Numbers | P | (as Goblin) | kept | - |
| | Ambush | P | During the first round of battle, this creature deals +30% Damage and enemies do not counterattack its attacks. | new keyword `opening_buff` (start_battle self buff, 1 round): buff `h3_kit_stronghold_ambush_effect` = qilin_wisp_buff_1 clone with `outAllDmgMod` 0.3 + `sequenceEffect: disable_counter` | Scurry |
| | Snare Trap | A 1/- | (old text) | kept (`keep_ability`) | - |
| Wolf Rider | Pack Hunt | P | Deals +20% Damage to an enemy that is adjacent to another friendly creature. | new plugin rule `flank` percent 20 | Pounce |
| Wolf Raider (Opener) | Double Strike | P | Attacks twice. | kept (HoMM3 identity) | - |
| | Pack Hunt | P | (as Wolf Rider) | `flank` 20 (line identity) | Pounce |
| Boar alt (Finisher) | Pack Hunt | P | (as Wolf Rider) | `flank` 20 (line identity) | Tusk Charge, Thick Hide |
| | Gore | A 1/1 | Performs a Melee attack that deals +15% Damage for each other friendly creature that has already acted this round, up to +60%. | `melee_strike` mult 1.0 counter true + new plugin rule `allies_acted` percent 15 cap 60, `abilityOnly` | Gore (+50%, -2 Defence) |
| Orc | Hamstring | A 1/1 | Performs a Ranged attack that deals 50% Damage. The target has -2 Speed until the end of the next round. | kept | - |
| Orc Chieftain (Opener) | Hamstring | A 2/1 | Performs a Ranged attack that deals full Damage. The target has -3 Speed until the end of the next round. | kept | - |
| | Pinning Volley | A 2/2 | Performs a Ranged attack that deals 60% Damage. The target cannot counterattack until the end of the round. | `shot` mult 0.6 counter false + new param `mech: reduce_counters 99` (donor h3_nix ability, `reduce_counters`) | Command Shot, Chieftain's Orders |
| Orc alt (Finisher) | Blood Rage | P | Whenever this creature takes Damage, it gains +3 Attack until the end of the next round. | kept | - |
| | Prey on the Weak | P | Deals +25% Damage to an enemy under any negative effect. | new plugin rule `vs_debuffed` percent 25 | Alert, Berserk Swing |
| Ogre | Clobber | A 2/2 | Performs a Melee attack. The target's abilities go on cooldown until the end of the next round. | new keyword `cooldown_strike`: `melee_strike` mult 1.0 + mechanic `force_unit_cd` (donor jaw ability, values copied) | Thick Hide |
| Ogre Mage (Opener) | Bloodlust | A 2/2 | Another friendly creature gains +6 Attack until the end of the next round. Does not end this creature's turn. | `stronghold_bloodlust` + new flag `free` (`actionCost` 0, as `kw_rally`) | Bloodlust (turn-ending) |
| | War Drums | P | At the start of battle, friendly creatures within 2 hexes gain +1 Speed until the end of the first round. | new keyword `opening_rally`: qilin start_battle action, `attack_rumble_x2` shape, ally buff `h3_kit_stronghold_war_drums_effect` (sub_skill_formation_2_buff clone, speed +1, 1 round) | Battle Chant, Thick Hide, Shaman's Ward |
| | Clobber | A 2/2 | (as Ogre) | `cooldown_strike` (line identity) | - |
| Ogre alt (Finisher) | Clobber | A 2/2 | (as Ogre) | `cooldown_strike` (line identity) | Thick Hide, Unstoppable |
| | Pulverize | A 2/2 | Performs a Melee attack. Against an enemy that has no counterattack left this round, it deals +50% Damage. | `melee_strike` mult 1.0 + new plugin rule `no_counter_left` percent 50, `abilityOnly` | Bone Breaker, Crushing Blow |
| Roc | Wing Buffet | P | Takes -20% Ranged Damage. | kept (line identity, the only `resist` left in the faction's flyers) | - |
| | Buffeting Wings | A 2/2 | Pushes every adjacent enemy 1 hex away. Does not end this creature's turn. | new keyword `push_burst`: minos_upg_alt ability 1 rumble shape, enemy target, mechanic `push_unit_from_caster` (donor minos ability), `actionCost` 0 | Swoop |
| Thunderbird (Finisher) | Wing Buffet | P | (as Roc) | kept | - |
| | Buffeting Wings | A 2/2 | (as Roc) | `push_burst` (line identity) | Swoop |
| | Lightning Strike | A 2/2 | Performs a Melee attack that deals Magic Damage: the target's Defence does not reduce it, but Magic resistances and immunities do. | new keyword `magic_strike`: `melee_strike` with `damageType_` magic_pure and tag `magic_damage` (donor shape: hive_queen magic_pure dealer) | Lightning Talons, Lightning Strike (+70%) |
| Roc alt (Opener) | Wing Buffet | P | (as Roc) | kept | - |
| | Buffeting Wings | A 2/2 | (as Roc) | `push_burst` (line identity) | Swoop, Double Strike |
| | Stoop | A 2/2 | Flies to any enemy on the battlefield and strikes it for full Damage. The enemy does not counterattack. | kept (`dive` range 99) | - |
| Cyclops | Rockslide | A 2/2 | Performs a Ranged attack that deals full Damage to the target and 50% Damage to every enemy adjacent to it. | `stronghold_area_shot` (moved down from the King) | Heavy Boulders, Boulder Smash |
| Cyclops King (Finisher) | Stone Fists | P | Receives no penalty in Melee range, dealing full Damage. | kept | - |
| | Rockslide | A 2/2 | (as Cyclops) | `stronghold_area_shot` (line identity) | - |
| | Siege Breaker | P | Deals +30% Damage to an enemy that is Defending or has any positive effect. | new plugin rule `vs_buffed` percent 30 | Heavy Boulders, Boulder Smash |
| Cyclops alt (Opener) | Sharpshooter | P | (shared keyword text) | kept | - |
| | Command: Fear | A 2/- | (old text) | kept (`keep_ability`) | - |
| | Baleful Gaze | A 2/1 | Performs a Ranged attack that deals 80% Damage. The target has -4 Attack until the end of the next round. | kept | Heavy Boulders |
| Behemoth | Armor Rend | P | Attacks ignore 30% of the target's Defence. | kept (HoMM3 identity) | - |
| | Unstoppable | P | Immune to all effects that restrict movement. | kept | - |
| Ancient Behemoth (Finisher) | Armor Rend | P | Attacks ignore 50% of the target's Defence. | kept | - |
| | Unstoppable | P | (as Behemoth) | kept | - |
| | Terrifying Presence | P | Adjacent enemy creatures have -3 Attack. | kept | - |
| | Rampage | P | When this creature destroys an enemy stack during its own turn, it immediately takes one more turn. At most once per round. | existing `bulwark_extra_turn` moved to a shared keyword `extra_turn_on_kill` (donor godslayer_upg_alt passive 0); taken from the Jotunn Warlord | Alert, Devastating Blow |
| Behemoth alt (Opener) | Armor Rend | P | Attacks ignore 45% of the target's Defence. | kept | - |
| | Unstoppable | P | (as Behemoth) | kept | - |
| | No Retaliation | P | (shared keyword text) | kept | - |
| | Phase Step | A 3/3 | Moves to any free hex on the battlefield. Does not end this creature's turn. | new keyword `phase_step`: h3_jotunn ability 0 (Clan Warp, `teleport`) retargeted to self, `actionCost` 0 | Spectral Pounce, Ethereal |

What each card asks of the player:

- **Openers:**
  - Ambush wants the Goblin alt in the front rank on turn one.
  - Pinning Volley strips the target's counterattack before the melee stacks swing.
  - War Drums is placement: stand allies around the Ogre Mage.
  - Free Bloodlust and Phase Step act in place, so the stack still gets its attack.
  - Buffeting Wings clears a pinned ally or opens a lane.
- **Finishers each cash in a different fact:**
  - Pile On: the target was already hit this round.
  - Gore: allies have already acted.
  - Prey on the Weak: the target is debuffed.
  - Pulverize: the target's counterattack is spent.
  - Siege Breaker: the target is buffed or Defending.
  - Lightning Strike: the target's Defence is high.
  - Rampage: a weakened stack is left to kill.

**Gallop count: 7 to 0. Armor Rend: 8 to 3, Behemoth line only, quantitatively distinct (30/50/45).**

## 3. New mechanics needed

- **Plugin rule `struck_this_round`** (Hobgoblin):
  - Caster side, +percent when the receiver has taken any Damage earlier in the current round.
  - Kept in a receiver-key set, filled in `DamagePercent` after the hit lands and cleared on the round dispatcher (start_round).
  - The current hit does not count itself.
- **Plugin rule `flank`** (Wolf line):
  - Caster side, +percent when the receiver has at least one adjacent creature of the caster's side other than the caster.
  - Reuses `Homm3RampartAvengerStrikeRuntime` adjacency: count the receiver's adjacent enemies and require at least 2, counting the caster.
- **Plugin rule `allies_acted`** (Gore):
  - Caster side, +percent per friendly stack, other than the caster, that has completed an action this round, up to cap.
  - Read from the round/action dispatcher that the Warcry runtime already hooks, as a per-side counter reset at round start. It counts actions, not Warcry, and reads no faction state.
  - `abilityOnly`: applies only when the committed attack is this unit's ability (ability-commit hook flag).
- **Plugin rule `vs_debuffed`** (Orc alt):
  - Caster side, +percent when the receiver carries any visible buff tagged `negative`.
  - Generalises `damage_vs_buff` from a sid list to a tag query on `Homm3BuffDebuffNativeAdapter`.
- **Plugin rule `vs_buffed`** (Cyclops King):
  - The mirror of `vs_debuffed`: any visible buff tagged `positive`, or the Defend state.
  - Defend's native buff is positive, so it counts if the adapter sees it. Otherwise check the defend flag the Warcry runtime already reads.
- **Plugin rule `no_counter_left`** (Pulverize):
  - Caster side, +percent when the receiver's remaining counterattacks this round are 0.
  - Read the unit's live counter count, the same field `reduce_counters` lowers. `abilityOnly`.
- **Keyword `opening_buff`** (Ambush):
  - `kw_start_buff` with a finite `duration` (the qilin `start_battle` action with buff duration 1, not -1).
  - New buff `h3_kit_stronghold_ambush_effect`, cloned from `qilin_wisp_buff_1`. Verified in Core: `units_buffs_nature.json` carries `data.sequenceEffect: disable_counter` on a unit buff.
  - Set: `infinite` false, `hidden` false, stats `{outAllDmgMod: 0.3}`, and `statOverrides` dropped.
- **Keyword `opening_rally`** (War Drums):
  - The qilin `start_battle` action with its dealer re-shaped to `attack_rumble_x2_x100` (or minos_upg_alt's rumble widened to radius 2), `castTarget_` allynoself.
  - Buff `h3_kit_stronghold_war_drums_effect` cloned from `sub_skill_formation_2_buff`: speed +1, maxDuration 1.
- **`shot` parameter `mech`** (Pinning Volley):
  - Appends a target mechanic to the shot dealer.
  - Verified donor: h3_nix ability carries `{"mech": "reduce_counters", "values": ["1"]}`. Use `"99"` so the target is left with none.
- **Keyword `cooldown_strike`** (Clobber):
  - `melee_strike` plus `force_unit_cd` on the target. The donor is the jaw line (`jaw_l.json`, which carries `force_unit_cd` in its ability and its `jaw_buff_1`).
  - Copy the values layout that puts every ability of the target on cooldown for 1 round.
- **`stronghold_bloodlust` flag `free`:** sets `actionCost` 0 and the view `infoDescription: ability_no_turn`, exactly as `kw_rally` does.
- **Keyword `push_burst`** (Buffeting Wings):
  - The `kw_rally` envelope (minos_upg_alt ability 1, `attack_rumble_x1_x100`, `actionCost` 0) with `castTarget_` enemy, no buff, and the targetMechanics `push_unit_from_caster ["false"]`.
  - The mechanic is verified on the minos ability in `minos_l.json`.
- **Keyword `magic_strike`** (Lightning Strike):
  - A `melee_strike` whose dealer has `damageType_: magic_pure` and the tag `magic_damage` in place of `normal_damage`.
  - 88 native dealers use magic_pure, for example hive_queen.
- **Shared keyword `extra_turn_on_kill`:** the existing `bulwark_extra_turn` body (godslayer_upg_alt passive 0, `unit_died` + `is_active_unit` + `add_action_points 1`, `maxAddedApPerRound` 1), moved into the shared table so that Stronghold can use it. Bulwark no longer does (see bulwark.md).
- **Keyword `phase_step`** (Behemoth alt):
  - h3_jotunn ability 0 (cast, `teleport`, ordered second pick = hex at `distanceFromFirst`). First pick: self. Distance: 99. `actionCost` 0.
  - Verified layout: `multitargetType` ordered, `numTargets` 2.
- **Retired buffs:** `h3_kit_stronghold_gored_effect`, `_shattered_effect`, `_reckless_effect` and `_orders_effect` are no longer used.

## 4. Power notes

A scratch run models each new card as a priced card with an offMult/toughMult guess. The table is `V:/olden_port_work/unit_rebalance/ability_pass/sfb/homm3_stronghold_draft.json`, the check output is `check_stronghold_draft.txt`, and the faction median moves from 0.98 to 0.90. Most rows lose priced power because the model cannot see plugin rules, and Alert, the resists and gallop are gone. So:

- **Grow:**
  - Roc alt, 0.79 after losing Double Strike and Swoop: +15% damage.
  - Roc, 0.82: +10% HP.
  - Wolf Rider, 0.84: +1 Attack.
  - Orc alt, 0.87 against the Chieftain's 0.99: +3 HP and +1 damage max.
  - Hobgoblin, 0.88 against the alt's 1.00: +1 Defence.
  - Behemoth alt: about +5% damage.
- **Hold:** Ogre line, Cyclops King, Ancient Behemoth.
  - Pulverize and Siege Breaker are conditional. With Pinning Volley in the army, Pulverize is near-certain, so give it an `offMult` of 1.15 rather than more body.
- **Watch:** Rampage on a tier 7 with 50% Armor Rend may be the strongest card in the faction. If the in-game check shows chain-killing, cut its body (HP -10%), not the card.

## 5. Risks

- **The plugin rules are unseen in game.** `struck_this_round`, `flank`, `allies_acted`, `vs_debuffed`, `vs_buffed` and `no_counter_left` are invisible to the AI and the damage forecast. Six new rules in one faction is a lot of hidden math. Vanilla prefers named visible mechanics, so each card text must state its condition exactly.
- **Reading live counterattacks and Defend state** (Pulverize, Siege Breaker) is unproven through interop. It may need an ilspy check of the counter field.
- **`disable_counter` and `outAllDmgMod`** have not been seen on a finite start_battle buff. It must expire after round 1 and must not keep `infinite`.
- **`push_burst` and `phase_step`** use native push and teleport. That is native, but the plan warns that code-driven push/teleport fails live. These are data, not code, but have not been seen on a free (actionCost 0) cast.
- **`magic_pure` on a melee dealer** may skip the Attack/Defence formula entirely (flat base damage). If it does, Lightning Strike needs `statDmgMult` tuning or becomes `armorPen` 1.0 on a self buff for one hit.
- **AI use of Pinning Volley:** the AI may waste it on targets that already have no counterattack.
