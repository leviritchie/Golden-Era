# Inferno (homm3_inferno): ability variety draft

Draft only (2026-11-21). Nothing here is built. Trade axis is unchanged: **Breacher** (striker: stands among enemies, no retaliation, Fire Shield) versus **Holder** (ward: durable, high Initiative, support, carries a short-handed round).

**Faction verb: punish movement.** Inferno's new shared vocabulary is **Burning**: a burning creature takes Magic Damage each time it moves. Three lines apply it in three different ways (an active shot, a splash on hit, and a zone around a ward), one line reads it (Efreeti), and the Hell Hounds hunt anything that moved this round. Enemies facing Inferno have to choose between holding still and taking damage. That choice is the faction's identity, and no other faction I drafted uses it.

## 1. Duplicates found

| Ability | Units | Why it is a duplicate or generic |
|---|---|---|
| `gallop` 0.05/0.10 (Pounce, Gore Charge, Burning Flight) | hell_hound, hound_upg, hound_upg_alt, demon_upg_alt, efreeti_upg | The same damage-per-hex across 3 lines. This is the overused pattern the owner named. |
| `counters` 2 "Alert" | hound_upg_alt, demon_upg, efreeti_upg_alt, devil_upg_alt | Every Holder line has the same second counterattack. |
| "Hit everything adjacent": `swirl_strike` (Rampage, Reaping Scythe), Whirling Lash (swirl pattern), Hellfire Burst (nova) | demon_upg_alt, devil_upg, pit_fiend_upg_alt, gog_upg_alt | Four whirlwinds in one faction. Rampage and Reaping Scythe are functionally identical. |
| `reach_strike` Lash | pit_fiend, pit_fiend_upg, pit_fiend_upg_alt | A Long Thrust equivalent on a whole line. |
| Generic `resist` (Small Target, Thick Hide, Hellborn, Heat Haze) | imp line, demon line, pit fiend line, efreeti_upg_alt | Flat damage reduction on four lines. Born of Flame (fire immunity) is identity and stays. |
| `melee_strike` +30% (Soul Rend), `shot` +30% (Fire Bolt on Gog and Magog) | pit_fiend_upg_alt, gog, gog_upg | Plain "hit harder" actives. Fire Bolt is copied on two rows. |
| Defence pile (Hold Fast -30%, Hardening, Thick Hide, Alert) | demon_upg | Four generic defensive cards on one row. |
| Aura of Dread -3 Attack | devil_upg | The same name and number as the Necropolis Black Knight alternate (one of my factions). |
| Familiar's Gift (mana transfer) | imp_upg_alt | Functionally identical to the Necropolis Wraith's Mana Channel (one of my factions). |
| Fire Shield as a timed self-buff | efreeti_upg | Fire Shield is a permanent passive in HoMM3. As a Focus button it sits right next to the alternate's Vengeance (an ally Fire Shield). |

## 2. Proposed kits

Focus/CD give the Focus cost and the cooldown in rounds. P = passive.

| Unit | Card | P / active | Card text | How it is built | Replaces |
|---|---|---|---|---|---|
| h3_imp | Heckle | P | Basic attacks and counterattacks give the target -1 Morale until the end of the next round. | `on_hit_buff`, new buff `h3_kit_inferno_heckled_effect` (cloneOf `hydra_debuff`, stats `moral: -1`, maxDuration 2) | Small Target |
| h3_imp_upg (Familiar) | Magic Channel | P | Whenever the enemy hero casts a spell, your hero gains 2 mana. | new kw `inferno_mana_echo`: the `cast_magic` / allegiance enemy action of `sub_skill_tactics_3_unit_bonus`, with the mech swapped to `change_mana ["add","ally","2","0","0","true"]` (the value form the Wraith's Spirit Feast row uses) | Magic Channel (mana-cost side modifier), Small Target |
| h3_imp_upg | Energize | 1 Focus, CD 1 | kept | kept | kept |
| h3_imp_upg_alt | No Retaliation | P | kept | kept | kept |
| h3_imp_upg_alt | Gang Up | P | Deals +12% Damage for every other friendly stack adjacent to the target, up to +36%. | new runtime rule `flanked` {percent 12, cap 36} | Small Target, Familiar's Gift |
| h3_gog | Fire Bolt | 1 Focus, CD 1 | Performs a Ranged attack that deals +15% Damage and sets the target Burning for 2 rounds: each time it moves, it takes 3 Magic Damage per Gog in the attacking stack. | `shot` mult 1.15, buff `h3_kit_inferno_burning_effect` (new, see section 3) | Fire Bolt (+30%) |
| h3_gog_upg (Magog) | Fireball | P | kept (Ranged attacks also hit every enemy adjacent to the target for 25% Damage.) | kept | kept |
| h3_gog_upg | Sharpshooter | P | kept | kept | kept |
| h3_gog_upg | Brimstone | P | Every enemy hit by a Ranged attack is set Burning until the end of the next round: each time it moves, it takes 2 Magic Damage per Magog in the attacking stack. | `on_hit_buff` with `h3_kit_inferno_burning_lesser_effect` (the area pattern carries the buff to the splash targets too) | Fire Bolt |
| h3_gog_upg_alt | Brawler | P | kept | kept | kept |
| h3_gog_upg_alt | Point Blank | P | kept | kept | kept |
| h3_gog_upg_alt | Hellfire Burst | 1 Focus, CD 2 | Deals Magic Damage to every adjacent enemy: 40% of a basic attack for each adjacent enemy, up to 160%. Enemies do not counterattack. | `inferno_nova` mult 0.4 plus new runtime rule `crowd_nova` {percent 100 per adjacent enemy, cap 400} that multiplies the ability's damage by the number of adjacent enemies | Hellfire Burst (flat 80%) |
| h3_hell_hound | Run Down | P | Deals +20% Damage to stacks that moved this round. | new runtime rule `moved_target` {percent 20} | Pounce |
| h3_hell_hound_upg (Cerberus) | Run Down | P | Deals +25% Damage to stacks that moved this round. | `moved_target` {25} | Pounce (10%) |
| h3_hell_hound_upg | Three Heads | P | kept | kept | kept |
| h3_hell_hound_upg | No Retaliation | P | kept | kept | kept |
| h3_hell_hound_upg_alt | Run Down | P | Deals +15% Damage to stacks that moved this round. | `moved_target` {15}. Its counterattacks qualify against every melee attacker that walked in. | Pounce, Alert |
| h3_hell_hound_upg_alt | Fire Breath | P | kept | kept | kept |
| h3_hell_hound_upg_alt | Snapping Jaws | P | kept (Counterattacks before the attacker strikes.) | kept | kept |
| h3_demon | Soul Tithe | P | When this stack is destroyed, your hero gains 3 mana. | new kw `inferno_death_mana`: peasant passive 0 (`unit_died`, allegiance self) with mechs `change_mana ["add","ally","3","0","0","true"]` | Thick Hide |
| h3_demon_upg (Horned Demon) | Soul Tithe | P | When this stack is destroyed, your hero gains 3 mana. | as above | Thick Hide |
| h3_demon_upg | Infernal Bargain | 1 Focus, CD 3 | Until the end of the round, this creature loses no creatures when hit. At the end of the round it takes 80% of the Damage dealt to it this round, all at once. Does not end this creature's turn. | `self_buff` with new buff `h3_kit_inferno_bargain_effect` cloneOf `magic_reality_distortion_effect_1` (stat `accumulateDamage`, `end_round` → `take_accumulated_damage ["0.8"]`) | Hold Fast, Hardening, Alert |
| h3_demon_upg_alt | Soul Tithe | P | When this stack is destroyed, your hero gains 3 mana. | as above | Thick Hide |
| h3_demon_upg_alt | Gore | P | kept (-3 Defence on hit) | kept | kept |
| h3_demon_upg_alt | Bloodied Fury | P | Deals +40% Damage for each full stack's worth of creatures it has lost this battle, up to +40%. | existing runtime `loss_fury` {percent 40, cap 40} | Gore Charge, Rampage |
| h3_pit_fiend | Crack the Whip | 1 Focus, CD 2 | An adjacent friendly stack gets +3 Attack and +2 Initiative until the end of the round. Does not end this creature's turn. | new kw `inferno_drive`: graverobber_upg_alt ability 1 (single-target cast) with cast/affect `allynoself`, range 1, `actionCost 0`, buff `h3_kit_inferno_driven_effect` (cloneOf `jaw_buff_2_upg`, stats offence 3, initiative 2, maxDuration 1) | Lash, Hellborn |
| h3_pit_fiend_upg (Pit Lord) | Crack the Whip | 1 Focus, CD 2 | A friendly stack within 2 hexes gets +3 Attack and +2 Initiative until the end of the round. Does not end this creature's turn. | `inferno_drive` range 2 | Lash, Overlord, Hellborn |
| h3_pit_fiend_upg | Raise Demons | 2 Focus, CD 3, 2 charges | Consumes a corpse within 3 hexes and raises Demons from it: one Demon for every 46 Health the fallen stack lost, up to 40 Health per Pit Lord. The Demons join your army for this battle. | new kw `inferno_raise_demons`: corpse cast from lich_upg_alt ability 1 (`targetCondition_ dead`, `destroy_corpse`) plus `summon_percent ["unit","h3_demon","ally",...]` from the peasant passive. The count is set by the new plugin rule `raise_by_hp` (section 3). | Animate Dead (kept vanilla revive) |
| h3_pit_fiend_upg_alt | Crack the Whip | 1 Focus, CD 2 | An adjacent friendly stack gets +3 Attack and +2 Initiative until the end of the round. Does not end this creature's turn. | `inferno_drive` range 1 | Whirling Lash, Lash, Hellborn |
| h3_pit_fiend_upg_alt | Flay | 2 Focus, CD 2 | Performs a Melee attack that strips every positive effect from the target before the Damage is dealt. | `melee_strike` mult 1.0 counter true, plus targetMechanics `dispel ["positive"]` (the value form native rows use) | Soul Rend |
| h3_efreeti | Born of Flame | P | kept | kept | kept |
| h3_efreeti | Hatred of Genies | P | kept | kept | kept |
| h3_efreeti | Fan the Flames | P | Deals +25% Damage to Burning creatures. | existing runtime `damage_vs_buff` {percent 25, buffs [burning, burning_lesser, scorched]} | Ifrit Spark (150% magic single-target cast, a plain strike) |
| h3_efreeti_upg (Sultan) | Born of Flame | P | kept | kept | kept |
| h3_efreeti_upg | Hatred of Genies | P | kept | kept | kept |
| h3_efreeti_upg | Fire Shield | P | Each enemy that attacks this creature in Melee takes 12 Magic Damage per creature in this stack. | existing `reflect` perCreature 12. It becomes permanent, as in HoMM3. | Fire Shield (timed self-buff), Burning Flight |
| h3_efreeti_upg | Sultan's Flame | 2 Focus | kept | kept | kept |
| h3_efreeti_upg_alt | Born of Flame | P | kept (-40%) | kept | kept |
| h3_efreeti_upg_alt | Hatred of Genies | P | kept | kept | kept |
| h3_efreeti_upg_alt | Scorched Earth | P | Enemies that end their movement adjacent to this creature are set Burning until the end of the next round. | new runtime rule `arrival_buff` {buff `h3_kit_inferno_scorched_effect`, radius 1}: the enemy end-of-move dispatcher | Heat Haze, Alert |
| h3_efreeti_upg_alt | Vengeance | 3 Focus | kept | kept | kept |
| h3_devil | (all four cards) | | kept: Blink, No Retaliation, Ill Omen, Hatred of Angels | kept | kept |
| h3_devil_upg (Arch Devil) | Blink, No Retaliation, Ill Omen, Hatred of Angels | P | kept | kept | kept |
| h3_devil_upg | Hellish Exchange | 3 Focus, CD 3 | Swaps places with an enemy stack within 6 hexes. That stack cannot counterattack until the end of the round. | `swap` variant (arbitrator_upg_alt `swap_units`) with the ordered second pick on `enemy`, `distanceFromFirst` 6, and a 1-round buff on that pick carrying `disablers [{ability: counter_attack, attack: all}]` (from `medusa_stone`) | Reaping Scythe, Aura of Dread |
| h3_devil_upg_alt | Blink, No Retaliation, Ill Omen, Unholy Resilience, Hatred of Angels | P | kept | kept | kept |
| h3_devil_upg_alt | Gate Anchor | 2 Focus | kept | kept | kept |
| h3_devil_upg_alt | (removed) | | | | Alert |

## 3. New mechanics needed

- **Burning buffs** (`h3_kit_inferno_burning_effect`, `_burning_lesser_effect`, `_scorched_effect`). These clone `magic_nairas_kiss_effect_1` (verified: it carries a `unit_end_move` / allegiance self action dealing `magic_pure` damage, alongside `unit_wait` and `unit_skip` actions). Keep only the `unit_end_move` action. Set `minBaseDmg`/`maxBaseDmg` to 0 and `minStackDmg`/`maxStackDmg` to 3, 2 and 2 per creature of the applying stack, the way `frog_poison` and Manticore Venom scale. Tag the buffs `negative` plus a new `burning_effect` tag, and **not** `overTime_effect`, so that Dungeon's Venom Burst (activate_all_buff_actions overTime) never detonates them. Durations are 2, 1 and 1.
- **`inferno_mana_echo`** (Familiar). Use the `sub_skill_tactics_3_unit_bonus` action as a unit passive (verified: trigger `cast_magic`, condition allegiance `enemy`, untargeted cast), with `add_energy` replaced by `change_mana` add 2 to ally. This matches HoMM3's Magic Channel better than the current mana-cost discount.
- **`inferno_death_mana`** (Soul Tithe). Use peasant passive 0 (verified: `unit_died`, allegiance self, `summon_percent` + `destroy_corpse`) with only a `change_mana` add mech. Keep the corpse: do not destroy it, because Raise Demons and Necropolis corpse users can still use it.
- **`inferno_drive`** (Crack the Whip). Use graverobber_upg_alt ability 1 (verified: single-target `cast`, `buffTarget_`) retargeted to `allynoself`. The buff clones `jaw_buff_2_upg`.
- **`inferno_raise_demons` + plugin rule `raise_by_hp`**. The data half is the corpse cast from `lich_upg_alt` ability 1 (verified as the corpse-to-mana cast the Necropolis keyword already clones) with `summon_percent` (peasant row form: `["unit","<sid>","ally","start_squad",factor,...]`) for `h3_demon`. `summon_percent` sizes from the dead stack's starting count, which would let a corpse of 200 Imps raise 100 Demons. The plugin hook on ability commit therefore overrides the summoned count: `floor(min(lostHP_of_corpse_stack, 40 * casterCount) / DemonHP)`. 2 charges per battle (the `charges` field, as Animate Dead uses it).
- **Runtime rule `flanked`** {percent, cap}: +percent per other friendly stack adjacent to the target, up to cap. Read at the damage step: count allied stacks other than the attacker on hexes adjacent to the target.
- **Runtime rule `moved_target`** {percent}: +percent if the target moved during the current round. Hook the move dispatcher to stamp a round number per stack. The brief lists "moved this turn" as possible through the same dispatchers Warcry uses.
- **Runtime rule `crowd_nova`** {percent, cap}: on this unit's ability damage only, scale damage by the number of enemies adjacent to the caster at commit. 1 enemy gives 40%, 4 give 160%.
- **Runtime rule `arrival_buff`** {buff, radius}: when an enemy stack ends a move within radius of this unit, add the buff to it. This is the same dispatcher as `moved_target`. The rule is passive, not queued, so it does not use the Avenger attack queue.
- **Hellish Exchange**. The `kw_swap` donor (`arbitrator_upg_alt` ability 0, verified `swap_units`) with the second ordered pick on `enemy`. This needs one in-game proof that `swap_units` accepts an enemy second pick.

Existing pieces reused: `loss_fury`, `damage_vs_buff`, `reflect`, `on_hit_buff`, `shot`, `self_buff`, `inferno_nova`, `magic_reality_distortion_effect_1` (verified: `accumulateDamage` stat + `end_round` `take_accumulated_damage 0.8`).

## 4. Power notes

These numbers come from a dry run with `unit_design_lab.py tune --design V:/olden_port_work/unit_rebalance/ability_pass/scratch_homm3_inferno.json`, with no write. New mechanics are priced as card entries with offMult/toughMult. Builder: `V:/olden_port_work/unit_rebalance/ability_pass/build_scratch_ide.py`.

- Removing `gallop` costs the most in the power model. Hell Hound bodies grow: base hp 25→27 (dmg 4-9), Cerberus 25→29 (4-10), and the alternate 26→27.
- Horned Demon: damage 9-13 → 11-16. Infernal Bargain is priced as toughness, and the row lost three defensive cards. Demon alternate: hp 46→50, 10-15.
- Pit Fiend 70→74 (16-24). Pit Fiend alternate 70→80 (17-26). Pit Lord is unchanged (Raise Demons is priced at toughMult 1.15).
- Efreeti 105→113, Sultan 116→125, Efreeti alternate 126→131.
- Arch Devil hp 308→350 (it loses a whirlwind and an aura). Devil alternate 290→309 (it loses Alert).
- Gog base cannot reach the band with Fire Bolt at 1.0 (0.84x). That is why the draft keeps Fire Bolt at +15% with Burning on top.
- The faction median after tuning is 0.96x and every unit lands in band.

## 5. Risks

- **Burning on `unit_end_move` inside a debuff.** Naira's Kiss proves the trigger works in a buff. I have not checked that a forced move (push, swap, teleport) also fires it. If it does, Hellish Exchange and enemy pushes would burn their targets, which is acceptable but should be checked.
- **`raise_by_hp` count override.** `summon_percent` on a corpse target has never been cast from an ability in this mod. The plugin has to rewrite the count before the summon resolves. The AI cannot see the rule and will undervalue Raise Demons.
- **`swap_units` with an enemy second pick** has not been proven. The enemy may also be swapped onto hazards such as an obstacle or a moat.
- **`accumulateDamage` on a unit buff.** It ships only on a spell. Deferred damage might skip creature losses in the damage forecast, and the AI may read the Horned Demon as invulnerable.
- **`moved_target` and `flanked`** are plugin rules, so the damage forecast will under-show Hound and Imp damage.
- **Soul Tithe** keeps the corpse. Check that two `unit_died` passives (Tithe + vanilla corpse logic) do not double-fire.
