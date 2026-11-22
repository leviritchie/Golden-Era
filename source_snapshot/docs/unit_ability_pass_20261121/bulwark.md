# Bulwark: ability variety draft (2026-11-21)

Draft only. Nothing here is built. Trade axis (unchanged):

- **Tempo** (striker): Initiative, Speed, free and repeatable small actions.
- **Bastion** (ward): front-loaded HP and Defence, payoffs for Defending and for being hit.

No card reads Runes.

The draft sharpens the split around **Focus economy**:

- Tempo units generate or hand out Focus on their own schedule: Wind Shear, Spirit Gift, Warlord's Command.
- Bastion units are fed by being hit: Runic Feedback, Pent-up Fury, Rune Brand, Stubborn Fleece.

## 1. Duplicates found

| Ability | Units | Why it is a duplicate or generic |
|---|---|---|
| "When this creature Defends, it gains X" (`bulwark_on_defend_buff`): Dig In, Lowered Horns, Steady Aim, Rune of Stone, Tusker Guard, Glacier Stance | Kobold alt, Ram alt, Steel Elf, Yeti Runemaster, War Mammoth, Jotunn alt | 6 of 7 Bastions share one trigger. They differ in number, not in how they play: every Bastion's best turn is Defend. |
| Damage per hex (`gallop` 0.05): Ram Charge, Trample | all 3 Rams, all 3 Mammoths | 6 rows. |
| Alert (`counters` 2) | Kobold Foreman, Argali, Mammoth alt | Generic. |
| Unlimited counterattacks (`counters` 999): Storm Reflexes, Battle Fury | Yeti alt, Jotunn Warlord | Neither creature had it in HoMM3. It also duplicates Fortress's Chaos Hydra. |
| Rallies (`rally`): Foreman Cadence (+1 Init/+1 Speed), Quickening Chant (+2 Init), Stoneskin Chant (+4 Def) | Kobold Foreman, Shaman alt, Great Shaman | Three adjacent-ally stat pulses. |
| On-hit Initiative chill: Frost Shot (-2), Freezing Shot (-3) | Snow Elf alt, Shaman alt | Same effect on two shooters. |
| Ice Bolt actives: Storm Frost (free), Freezing Hex (turn-ending) | Yeti alt, Shaman alt | Same spell twice. |
| Full heal stacked on full heal: Rune Surge plus Regeneration | Yeti Runemaster | Regeneration already restores full HP every turn, so Rune Surge mostly duplicates it. |
| Taunt: Bellow | War Mammoth | The same `ent_taunt_buff` clone as Fortress's Menacing Hiss. |
| `resist`: Small Target, Aurora Fleece, Steel Mail, Spirit Ward, Thick Hide, Glacial Hide; plus Totem of Stone (`aura` -15% Melee) | 3 Kobolds, Ram alt, Steel Elf, 3 Shamans, 3 Mammoths, Jotunn alt, Great Shaman | 13 generic damage-reduction rows. |
| Conqueror (extra turn on a kill) | Jotunn Warlord | Moved to Stronghold's Ancient Behemoth (Rampage), where "finish the weakened stack" is the trade axis. |

## 2. Proposed kits

| Unit | Card | P / A | Card text | How it is built | Replaces |
|---|---|---|---|---|---|
| Kobold | Small Target | P | Takes -20% Ranged Damage. | kept (line identity) | - |
| Kobold Foreman (Tempo) | Small Target | P | (as Kobold) | kept | - |
| | Foreman Cadence | A 1/2 | Adjacent friendly creatures gain +1 Initiative and +1 Speed until the end of the round. Does not end this creature's turn. | kept (now the faction's only rally) | - |
| | Shift Change | A 1/2 | Swaps places with a friendly creature within 3 hexes. Does not end this creature's turn. | `swap` range 3 + new flag `free` (`actionCost` 0) | Alert |
| Kobold alt (Bastion) | Small Target | P | (as Kobold) | kept | - |
| | Rune Brand | P | Whenever this creature takes Damage, it gains +1 Defence until the end of the battle. | kept | - |
| | Dig In | P | When this creature Defends, it takes -25% Damage until the end of the next round. | kept (Defend payoff 1 of 3: survive) | - |
| Mountain Ram | Sure-Footed | P | Moves over obstacles. | new keyword `sure_footed`: unit stat `ignoreObstacles` true (donor stat: qilin_selfbuff) | Ram Charge |
| Argali (Tempo) | Ice Immunity | P | Immune to Ice Bolt Damage and its Initiative reduction, and to Avalanche Damage. | kept | - |
| | Sure-Footed | P | (as Mountain Ram) | `sure_footed` (line identity) | Ram Charge |
| | Butt and Bound | A 1/1 | Performs a Melee attack, then returns to its original position. | kept | Alert |
| Ram alt (Bastion) | Ice Immunity | P | (as Argali) | kept | - |
| | Sure-Footed | P | (as Mountain Ram) | `sure_footed` | Ram Charge |
| | Stubborn Fleece | P | The first attack against this creature each round deals -50% Damage. | new plugin rule `first_hit_ward` percent 50 | Aurora Fleece, Lowered Horns |
| Snow Elf | Duelist | P | Receives no penalty in Melee range, dealing full Damage. | kept | - |
| Steel Elf (Bastion) | Duelist, Free Shooting | P | (as now) | kept | Steel Mail |
| | Steady Aim | P | When this creature Defends, it gains +3 Attack and its Ranged attacks deal full Damage at any range until the end of the next round. | kept (Defend payoff 2 of 3: shoot) | - |
| Snow Elf alt (Tempo) | Duelist, Frost Shot, Free Shooting, Countershot | P | (as now) | kept (now the only on-hit chill) | - |
| Yeti | Regeneration | P | Restores to full HP at the start of its turn. This cannot revive fallen units. | kept | - |
| | Shrug Off | P | Negative effects on this creature last at most 1 round. | kept | - |
| Yeti Runemaster (Bastion) | Regeneration, Shrug Off | P | (as Yeti) | kept | - |
| | Runic Feedback | P | Gains 1 more Focus each time it takes Damage. | unit stat `energyPerTakeDamage` 2, base 1 (a stat on every native unit block) | Frost Rune |
| | Glacial Rune | A 2/3 | Until the end of the round, Damage this creature takes is held back and dealt to it all at once when the round ends. Does not end this creature's turn. | `self_buff` with new buff `h3_kit_bulwark_glacial_rune_effect` = clone of `magic_reality_distortion_effect_0` (`accumulateDamage` true + `end_round` `take_accumulated_damage 1.0`), maxDuration 1 | Rune of Stone, Rune Surge |
| Yeti alt (Tempo) | Regeneration, Shrug Off | P | (as Yeti) | kept | - |
| | Storm Fury | P | Each basic attack and counterattack this creature makes gives it +1 Attack until the end of the battle. | kept | - |
| | Storm Frost | A 2/- | (old text: Ice Bolt, does not end the turn) | kept (now the faction's only Ice Bolt) | Storm Reflexes |
| Shaman | Spirit Ward | P | Takes -20% Magic Damage. | kept (line identity) | - |
| | Air Ward | A 2/- | (old text) | kept | - |
| Great Shaman (Bastion) | Spirit Ward | P | Takes -25% Magic Damage. | kept | - |
| | Air Ward | A 2/- | (old text) | kept | - |
| | Spirit Wash | A 2/3 | Dispels all negative effects from one friendly creature within 3 hexes. | kept | - |
| | Spirit Anchor | P | The number of creatures in each adjacent friendly stack cannot fall below half of what it had at the start of the round. | new keyword `anchor_aura`: `aura` radius 1 allynoself with buff `h3_kit_bulwark_spirit_anchor_effect` = clone of `magic_arinas_chosen_effect_0` (`healthLimitMinPercent` 50, its extra action removed), refreshed at `start_round` | Totem of Stone, Stoneskin Chant |
| Shaman alt (Tempo) | Spirit Ward | P | (as Shaman) | kept | - |
| | Wind Shear | P | Gains 1 Focus at the start of each round. | unit stat `energyPerRound` 1 (native unit stat) | Freezing Shot |
| | Spirit Gift | A 1/1 | Another friendly creature within 4 hexes gains 2 Focus. Does not end this creature's turn. | new keyword `focus_gift`: `kw_rally` single-target variant (`attack_single_buff`, allynoself, range 4, `actionCost` 0) with mechanic `add_energy ["2"]` (donor: godslayer_upg `add_energy`) | Freezing Hex, Quickening Chant |
| Mammoth | Thick Hide | P | Takes -25% Ranged Damage. | kept (line identity) | - |
| | Trample | P | Basic attacks also hit the creature directly behind the target for 50% Damage. | new keyword `pierce_attack`: default attack and counterattack `attackPatternSid` → `attack_reach_x1_x100_x50`, enemies only | Trample (gallop) |
| War Mammoth (Bastion) | Thick Hide, Trample | P | (as Mammoth) | kept / `pierce_attack` | Trample (gallop) |
| | Unyielding | P | Once per battle, when an attack would destroy this stack, the number of creatures in it stays as it was before that attack. | kept | - |
| | Pent-up Fury | P | Each attack this creature takes adds +10% Damage to its next attack, up to +50%. The bonus is used up when it attacks or counterattacks. | new plugin rule `stored_fury` percent 10 cap 50 | Tusker Guard, Bellow |
| Mammoth alt (Tempo) | Thick Hide, Trample | P | (as Mammoth) | kept / `pierce_attack` | Trample (gallop), Alert |
| | Run Them Down | P | Attacks any enemy that walks or flies away from a hex next to this creature. This works like a counterattack but does not use one up. | kept | Tusk Sweep |
| Jotunn | Frostbound Skies, Ice Immunity, Clan Warp | P / A | (as now) | kept | - |
| Jotunn Warlord (Tempo) | Frostbound Skies, Ice Immunity | P | (as now) | kept | - |
| | Clan Warp | A 2/2 | (old text) | kept | - |
| | Warlord's Command | A 3/3 | Another friendly creature gains one more turn this round. Does not end this creature's turn. | new keyword `grant_turn`: single ally cast (`attack_single_buff`, allynoself), `actionCost` 0, mechanic `add_action_points ["1"]` (donors: trickster_buff, unspeakable_buff carry `add_action_points`) | Battle Fury, Conqueror, Sundering Blow |
| Jotunn alt (Bastion) | Frostbound Skies, Ice Immunity, Winter's Grasp | P | (as now) | kept | Glacial Hide |
| | Glacier Stance | P | When this creature Defends, it gains +5 Defence and 2 more counterattacks per round until the end of the next round. | kept (Defend payoff 3 of 3: retaliate) | - |
| | Avalanche | A 3/- | (old text) | kept | - |

What each card asks of the player:

- **Tempo:**
  - Shift Change and Foreman Cadence let the Foreman reorder the line, then still attack.
  - Sure-Footed rams take paths no one else can.
  - Wind Shear plus Spirit Gift turn the Shaman alt into the army's Focus battery.
  - Warlord's Command hands a fresh turn to whichever stack is in the best spot.
- **Bastion:**
  - Stubborn Fleece wants the ram hit by many weak attacks, not one big one.
  - Glacial Rune holds a Runemaster's line for a whole round before the bill comes.
  - Runic Feedback makes being hit pay for Glacial Rune.
  - Spirit Anchor is positional: stack your best units around the Great Shaman.
  - Pent-up Fury turns a turn of soaking into one heavy blow.
  - Defend payoffs are down to three, each different: survive (Dig In), shoot (Steady Aim), retaliate (Glacier Stance).

**Defend payoffs: 6 to 3. Gallop: 6 to 0. Alert: 3 to 0. Unlimited counters: 2 to 0. Rallies: 3 to 1. Resist: 13 to 9, and those are the Kobold, Shaman and Mammoth line identities, one per row.**

## 3. New mechanics needed

- **Keyword `sure_footed`:**
  - Writes `stats.ignoreObstacles: true` on the unit block. It is native only on a buff (qilin_selfbuff, "Mist Form").
  - If the unit-block stat is ignored, fall back to a `start_buff` with a qilin_selfbuff clone that keeps only `ignoreObstacles` (no `maxInDmg`).
- **Plugin rule `first_hit_ward`** (Stubborn Fleece):
  - Receiver side, -percent on the first damaging hit this receiver takes each round.
  - Per-receiver flag set in `DamagePercent` and cleared on start_round. Damage over time and spells count as hits.
- **`swap` flag `free`:** `actionCost` 0 on the arbitrator_upg_alt `swap_units` ability (`kw_swap` currently pops `actionCost`).
- **Unit stats `energyPerTakeDamage` 2** (Runemaster) **and `energyPerRound` 1** (Shaman alt):
  - Both stats are present on every native unit stat block (for example griffin_upg_alt `energyPerTakeDamage` 1, `energyPerRound` 0).
  - Needs a tiny keyword `focus_stat` that writes the value and adds a card, because the rebuild may reset these stats.
- **Buff `h3_kit_bulwark_glacial_rune_effect`** (Glacial Rune):
  - A clone of `magic_reality_distortion_effect_0`, verified: `data.stats.accumulateDamage` true, action `end_round` → `take_accumulated_damage ["1.0"]`.
  - Set: `canDispel` false (so Spirit Wash cannot clear the bill), name "Glacial Rune", maxDuration 1.
- **Keyword `anchor_aura`** (Spirit Anchor):
  - `aura` with a buff cloned from `magic_arinas_chosen_effect_0` (verified stat `healthLimitMinPercent`; text "Number of creatures can't fall below {0}% of what the stack had when the spell was cast").
  - Drop the `_special` extra action. The aura re-applies the buff each round, so the baseline is "start of the round or when it stepped adjacent".
- **Keyword `focus_gift`:**
  - A single-ally free cast carrying `add_energy ["2"]`. The donor value layout is godslayer_upg and hive_queen_upg_alt (`add_energy`, 23 native rows).
  - Range 4 via `shootRange` on the cast.
- **Keyword `pierce_attack`** (Trample):
  - Re-points the default attack and counterattack `attackPatternSid` to `attack_reach_x1_x100_x50` (a Core attack pattern) with `affectTargetParams.castTarget_` enemy.
  - This is the Breath shape at 50%. It is the Mammoth's identity, not Breath: no fire, no ally hit.
- **Plugin rule `stored_fury`** (Pent-up Fury):
  - Per-holder counter, +1 each time the holder takes a damaging hit from a unit.
  - On the holder's next outgoing attack or counterattack, add percent × counter (capped), then reset to 0.
  - Lives beside `GrudgeByHolder` in `Homm3UnitKitRuntime`.
- **Keyword `grant_turn`** (Warlord's Command):
  - A free single-ally cast with `add_action_points ["1"]`, as trickster_buff and unspeakable_buff carry it.
  - The target needs `maxAddedApPerRound` ≥ 1 for the round. Write it into the granted buff's stats, as godslayer_upg_alt's passive does.
- **Retired:**
  - Buffs: `h3_kit_bulwark_lowered_horns_effect`, `_rune_of_stone_effect`, `_tusker_guard_effect`, `_bellow_effect`, `_stoneskin_effect`, `_quickening_effect`.
  - Keyword: `bulwark_extra_turn` (moves to the shared `extra_turn_on_kill`, see stronghold.md).

## 4. Power notes

Scratch run: `V:/olden_port_work/unit_rebalance/ability_pass/sfb/homm3_bulwark_draft.json`. The faction median moves from 0.94 to 0.92.

- **Gate errors (all fixable with the body):**
  - Mammoth alt at 0.81, which lost Alert and Tusk Sweep: +12% damage and +1 Initiative, so the Tempo mammoth stays the faster one.
  - Great Shaman 0.92 against Shaman alt 1.06: drop the Shaman alt by 1 Attack, or raise the Great Shaman `toughMult` on Spirit Anchor to about 1.15. Anchor is strong on a stacked line, and the model sees only the 1.08 guess.
- **Grow:**
  - Jotunn Warlord (0.86): +8% damage. Warlord's Command is priced only as `offMult` 1.15, but a free extra turn for a tier 6 or 7 ally is worth more, so keep the body change small and re-check after the lab prices it.
  - Mountain Ram (0.87): +1 Attack.
- **Watch:**
  - Glacial Rune on a Regeneration body can make the Runemaster nearly unkillable inside one round, and then it regenerates the top creature. The damage still lands at round end, so it is a delay, not a heal. Watch it in game.
  - Wind Shear plus Spirit Gift doubles one ally's Focus income. With Warlord's Command (3 Focus) in the same army, the Shaman alt can fund a Command every three rounds. That is intended Tempo, but the cooldown is the safety valve.

## 5. Risks

- **`accumulateDamage` on a unit-cast self buff** has been seen only as a hero spell (Reality Distortion). Whether Regeneration at the start of the yeti's turn runs before or after the end-of-round bill is unproven.
- **`healthLimitMinPercent` re-applied by an aura:** each refresh may reset the "when cast" baseline, which would make the stack unkillable while adjacent. If so, apply it only at `start_round` (hidden passive) instead of through the aura.
- **`add_action_points` on a non-active ally:** whether the game gives that ally an extra turn this round, or only the next time its turn comes, is unproven. The card text says "one more turn this round" and must be checked.
- **`ignoreObstacles` as a unit stat** is unproven (native only as a buff). The pathfinder and the AI may still route around obstacles.
- **`first_hit_ward` and `stored_fury`** are plugin rules, invisible to the AI and the forecast.
- **`pierce_attack`:** the counterattack also uses the pierce shape. That may hit a second enemy behind the attacker, which is intended, but it is unseen with `triggerCounter` chains.
